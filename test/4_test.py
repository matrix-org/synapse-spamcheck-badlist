import logging
import uuid
import urllib
import sys
import time

import requests

logging.basicConfig(filename = "/data/test.log")
logger = logging.getLogger("synapse_spamcheck_badlist.test")


class Test:
    def __init__(self):
        self.access_token = None
        self.room_id = None

    def _item_generator(self, json_input, lookup_key):
        """
        Walk recursively through a json object looking for instances of a given key.
        """
        if isinstance(json_input, dict):
            for k, v in json_input.items():
                if k == lookup_key:
                    yield v
                else:
                    yield from self._item_generator(v, lookup_key)
        elif isinstance(json_input, list):
            for item in json_input:
                yield from self._item_generator(item, lookup_key)


    # Further setup
    def setup(self):
        logger.info('Authenticating')

        authentication = requests.post('http://localhost:8080/_matrix/client/r0/login', json = {
            'type': 'm.login.password',
            'identifier': {
                'type': 'm.id.user',
                'user': 'user_1'
            },
            'password': 'user_1',
        }).json()
        logger.info('Authentication %s' % authentication)
        self.access_token = 'Bearer %s' % authentication['access_token']


        # 1b. Creating the room.

        logger.info('Creating public room')

        room_creation = requests.post('http://localhost:8080/_matrix/client/r0/createRoom', json = {
            'visibility': 'public',
        }, headers = {
            'Authorization': self.access_token
        }).json()
        logger.info('Room creation %s' % room_creation)
        self.room_id = room_creation['room_id']
        self.quoted_room_id = urllib.parse.quote(self.room_id)

        logger.info('Created room %s' % self.room_id)


    def _send_message_to_room(self, prefix, json):
        """
        Send a message to the room we're using for this test.

        Argument `prefix` is prepended to the message id, to aid with looking up
        stuff in the Synapse logs.
        """
        response = requests.put('http://localhost:8080/_matrix/client/r0/rooms/%s/send/m.room.message/%s-%s' % (self.quoted_room_id, prefix, uuid.uuid1()),
            json = json,
            headers = {
                'Authorization': self.access_token
            }
        ).json()
        return response.get('event_id', None)

    def _upload_content(self, prefix, content):
        """
        Upload a file.

        Argument `prefix` is prepended to the file name, to aid with looking up
        stuff in the Synapse logs.
        """
        response = requests.post('http://localhost:8080/_matrix/media/r0/upload?filename=%s-%s' % (prefix, uuid.uuid1()),
            headers = {
                'Authorization': self.access_token,
                'Content-Type': 'application/binary',
            },
            data = content
        ).json()
        return response.get('content_uri', None)

    def _sync_with_server(self, since):
        """
        Request all events since `since` from the server, or all events if `since` is `None`.

        Returns a pair `new_since, response`.
        """
        response = requests.get('http://localhost:8080/_matrix/client/r0/sync', json = {
            'since': since
        }, headers = {
                'Authorization': self.access_token
            }
        ).json()
        return response.get('since', None), response

    # 2. Starting actual test
    def test(self):
        logger.info("Testing with room %s, access token %s" % (self.quoted_room_id, self.access_token))

        # A mapping of event_id => description for good events. They should be preserved in history.
        good_events = {}
        # A mapping of event_id => description for bad events. They should either be intercepted before they reach history or be redacted from history.
        bad_events = {}

        logger.info('Sending raw text, it should pass')
        event_id = self._send_message_to_room(
            'raw',
            {
                'body': 'A text without any link',
                'format': 'org.matrix.custom.html',
                'formatted_body': 'A rich text without any link',
                'msgtype': 'm.text'
            }
        )
        good_events[event_id] = "raw text"


        logger.info('Sending with good URLs, it should pass')
        event_id = self._send_message_to_room(
            'good-url',
            {
                'body': 'A text with a good link to good.example.com',
                'format': 'org.matrix.custom.html',
                'formatted_body': 'A text with a good link to <a href="http://good.example.com">good.example.com</a>',
                'msgtype': 'm.text'
            }
        )
        good_events[event_id] = "good URL"

        logger.info('Sending text with bad url in body, it should be rejected')
        event_id = self._send_message_to_room(
            'evil-hidden-link-in-body',
            {
                'body': 'A text with a hidden link to evil.example.com',
                'format': 'org.matrix.custom.html',
                'formatted_body': 'A rich text without any link',
                'msgtype': 'm.text'
            }
        )
        if event_id is None:
            logger.info('Message was rejected immediately')
        else:
            # Message may be redacted later
            bad_events[event_id] = "bad URL in body"

        logger.info('Sending text with bad url in formatted_body, it should be rejected')
        event_id = self._send_message_to_room(
            'evil-hidden-link-in-formatted_body',
            {
                'body': 'A text without any link',
                'format': 'org.matrix.custom.html',
                'formatted_body': 'A rich text with a hidden link to evil.example.com/1234',
                'msgtype': 'm.text'
            }
        )
        if event_id is None:
            logger.info('Message was rejected immediately')
        else:
            # Message may be redacted later
            bad_events[event_id] = "bad URL in formatted_body"

        with open('test/good_file.bin', mode='rb') as file:
            good_file_content = file.read()

        with open('test/evil_file.bin', mode='rb') as file:
            evil_file_content = file.read()

        logger.info('Upload a good image, it should be accepted')
        good_mxid = self._upload_content('good', good_file_content)
        logger.info('Good image is %s' % good_mxid)

        logger.info('Upload a bad image, it should be rejected')
        evil_mxid = self._upload_content('evil', evil_file_content)
        assert evil_mxid is None


        for message_type in ['m.file', 'm.image', 'm.audio']:
            logger.info('Send good image with good description, it should be accepted')
            event_id = self._send_message_to_room(
                'good-image',
                {
                    'body': 'A text without any link',
                    'msgtype': message_type,
                    'url': good_mxid,
                    'info': {
                        'w': 320,
                        'h': 200,
                        'size': len(good_file_content),
                    }
                }
            )
            good_events[event_id] = "Good image with good description, type %s" % message_type

            logger.info('Send good image with bad description, it should be rejected')
            event_id = self._send_message_to_room(
                'good-image-with-evil-description',
                {
                    'body': 'An text with a hidden link to evil.example.com',
                    'msgtype': message_type,
                    'url': good_mxid,
                    'info': {
                        'w': 320,
                        'h': 200,
                        'size': len(good_file_content),
                    }
                }
            )
            if event_id is None:
                logger.info('Message was rejected immediately')
            else:
                # Message may be redacted later
                bad_events[event_id] = "Good image with bad description, type %s" % message_type

        logger.info('Sending canary event, to ensure that all previous events have been flushed')
        event_id = self._send_message_to_room(
            'canary-event',
            {
                'body': 'A text without any link',
                'format': 'org.matrix.custom.html',
                'formatted_body': 'A rich text without any link',
                'msgtype': 'm.text'
            }
        )
        canary_event = event_id

        # Wait until the canary has been treated.
        since = None
        while True:
            since, response = self._sync_with_server(since)
            found_canary = False
            for id in self._item_generator(response, 'event_id'):
                if id == canary_event:
                    found_canary = True
                    break
            if found_canary:
                break
            # Otherwise, wait a little.
            logger.info("Apparently, not all events have been flushed, waiting a bit")
            time.sleep(0.5)

        # Now that we're sure that all events have been treated, re-download all events
        # and make sure that the good ones are all present and the bad ones are all either
        # absent or redacted away.
        # If we were certain that all bad events were redacted immediately, we could do
        # this as part of the first canary loop.
        logger.info("Now checking that all good events have passed and all bad events have been rejected")
        since = None
        bad_events_found = set()
        while True:
            since, response = self._sync_with_server(since)
            found_canary = False

            # Ensure that all the good events are present
            for id in self._item_generator(response, 'event_id'):
                logger.info("Encountering event id %s" % id)
                if id == canary_event:
                    found_canary = True
                if id in good_events:
                    logger.info("Found good event: %s" % good_events[id])
                    del good_events[id]
                if id in bad_events:
                    logger.info("Found bad event: %s" % bad_events[id])
                    bad_events_found.add(bad_events[id])

            # Ensure that all the bad events that are present are redacted away
            for id in self._item_generator(response, 'redacts'):
                logger.info("Event %s has been redacted" % id)
                bad_events_found.remove(id)

            if found_canary:
                break
            # Otherwise, continue downloading.

        # By now, we should have found all the good events and none of the bad events.
        logger.info("Let's see if there's any good event that we haven't found: %s" % good_events)
        assert len(good_events) == 0

        logger.info("Let's see if there's any bad event that hasn't been intercepted or redacted: %s" % bad_events_found)
        assert len(bad_events_found) == 0

if __name__ == "__main__":
    try:
        test = Test()
        test.setup()
        test.test()
    except Exception as e:
        logger.info("TEST FAILED: %s" % e)
        sys.exit(-1)
    logger.info("TEST SUCCEEDED")
    sys.exit(0)
