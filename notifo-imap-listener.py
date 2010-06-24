#!/usr/bin/env python
# vim:ts=4:sw=4:expandtab:ft=python:fileencoding=utf-8
"""Notifo IMAP Listener

Monitors address for new mail and forwards it to notifo.

"""

__version__ = "0.1"

import sys
import traceback
import imaplib
import email.parser
import urllib
import urllib2
import json
import time
import logging
from base64 import encodestring
from ConfigParser import ConfigParser


class ImapMonitor():
    """The class that monitors the mail account"""
    
    def __init__(self, user, password, server='localhost', ssl=True):
        self.logger = logging.getLogger('ImapMonitor')
        self.server = server
        self.ssl = ssl
        self.user = user
        self.password = password
        self.notifo = Notifo()
        # if you get errors here, make sure server supports SSLv2
        self.logger.info('Connecting...')
        self.mail = imaplib.IMAP4_SSL(host=server)
        #self.mail.debug = 4
        self.logger.info('Logging in...')
        self.mail.login(user, password)
        self.logger.debug('Success')

    def _handle_error(self, error=None):
        self.logger.critical(error)
        self.cleanup()
        sys.exit(1)
        
    def cleanup(self):
        self.logger.debug('Logging out')
        self.mail.logout()
    
    def run_once(self):
        self.mail.select()
        typ, msgnums = self.mail.search(None, 'UNSEEN')
        #typ, msgnums = self.mail.search(None, 'ALL')
        if typ != 'OK':
            self._handle_error('Did not receive ok from server (search): %s' % typ)
        for num in msgnums[0].split():
            self.logger.debug('Received new email')
            #typ, header = self.mail.fetch(num, '(BODY.PEEK[HEADER])')
            #if typ != 'OK':
            #    self._handle_error('Did not receive ok from server (fetch header): %s' % typ)
            #typ, body = self.mail.fetch(num, '(BODY.PEEK[TEXT])')
            #if typ != 'OK':
            #    self._handle_error('Did not receive ok from server (fetch body): %s' % typ)
            typ, rfc = self.mail.fetch(num, '(RFC822)')
            if typ != 'OK':
                self._handle_error('Did not receive ok from server (fetch rfc): %s' % typ)
            # Above auto marks as seen, this reverses that and makes it new again
            #typ, data = self.mail.store(num, '-FLAGS', '\\Seen')
            msg = email.parser.Parser().parsestr(rfc[0][1])
            text = ''
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        text = text + part.get_payload()
            else:
                text = msg.get_payload()
            text = text.strip()
            self.logger.debug('Text sent to notifo: %s' % text)
            # TODO: if something fails the message won't retry
            self.notifo.send_notification(msg=text)
            #print '-----'
            #print text
            #print '-----'
        
    def run_forever(self):
        self.logger.info('Running forever, use ctrl-c to cancel')
        while True:
            self.run_once()
            # Wait for one second so we don't hammer the mail server
            time.sleep(1)


class Notifo():
    """Basic notifo interface (didn't bother with subscription request)."""
    def __init__(self):
        self.logger = logging.getLogger('Notifo')
        self.base_url = 'https://api.notifo.com/v1/'
        config = ConfigParser()
        config.read('config.ini')
        self.username = config.get('notifo', 'username')
        self.secret = config.get('notifo', 'secret')
        self.label = config.get('notifo', 'label')
    
    def send_notification(self, to=None, msg=None, label=None, title=None, uri=None):
        data = {}
        if to is not None:
            data['to'] = to
        if msg is not None:
            data['msg'] = msg
        else:
            self.logger.info('no message specified, aborting.')
            return False
        if label is not None:
            data['label'] = label
        else:
            data['label'] = self.label
        if title is not None:
            data['title'] = title
        if uri is not None:
            data['uri'] = uri
            
        auth = encodestring('%s:%s' % (self.username, self.secret))
        values = urllib.urlencode(data)
        request = urllib2.Request(self.base_url + 'send_notification', values)
        request.add_header('Authorization', 'Basic %s' % auth.rstrip())
        try:
            response = urllib2.urlopen(request)
        except urllib2.HTTPError, e:
            # may have an error for why it doesn't work
            self.logger.error(e.fp.readline())
            return None
        except urllib2.URLError, e:
            # a non http error, may be a typo
            self.logger.error(e.reason)
            return None
        try:
            result = json.loads(response.read())
        except ValueError, e:
            self.logger.error('Error parsing response: %s' % e)
        
        if result['status'] == 'success':
            self.logger.debug('Message sent successfuly')
            return True
        else:
            self.logger.error(result['status'])
            return None
    
            
def main():
    config = ConfigParser()
    config.read('config.ini')
    #username = config.get('jabberbot', 'username')
    #password = config.get('jabberbot', 'password')
    #adminjid = config.get('jabberbot', 'adminjid')
    imap_server = config.get('mail', 'server')
    imap_ssl = config.getboolean('mail', 'ssl')
    imap_user = config.get('mail', 'user')
    imap_password = config.get('mail', 'password')
    
    # configure logging
    LEVELS = {'debug': logging.DEBUG,
              'info': logging.INFO,
              'warning': logging.WARNING,
              'error': logging.ERROR,
              'critical': logging.CRITICAL}
    level = LEVELS.get(config.get('logging', 'level'), logging.NOTSET)
    logging.basicConfig(level=level,
                        format="%(asctime)s: %(name)s: %(levelname)s: %(message)s",
                        filename=config.get('logging', 'file'),
                        filemode='a')
    consolelog = logging.StreamHandler()
    consolelog.setLevel(level)
    consolelog.setFormatter(logging.Formatter("%(levelname)-8s: %(message)s"))
    logging.getLogger('').addHandler(consolelog)
    logmain = logging.getLogger('main')
    
    monitor = ImapMonitor(server=imap_server, ssl=imap_ssl, user=imap_user, 
                          password=imap_password)
    while True:
        try:
            monitor.run_forever()
        except imaplib.IMAP4.abort, e:
            # server error, need to start over
            logmain.warning("Server error: %s " % e)
            logmain.info("reconnecting in 30 seconds")
            time.sleep(30)
            monitor.__init__(server=imap_server, ssl=imap_ssl, user=imap_user, 
                             password=imap_password)
        except KeyboardInterrupt, e:
            # Ctrl-c
            logmain.debug('Received ctrl-c or SIGINT, cleaning up')
            monitor.cleanup()
            # not raising since everything has been handled
            sys.exit(0)
    

if __name__ == "__main__":
    # TODO: run cleanup function if needed
	try:
		main()
	except KeyboardInterrupt, e:
		# Ctrl-c
        raise e
	except SystemExit, e:
		# sys.exit()
		raise e
	except Exception, e:
		print "ERROR, UNEXPECTED EXCEPTION"
		print str(e)
		traceback.print_exc()
		sys.exit(1)
	else:
		# Main function is done, exit cleanly
		sys.exit(0)

