import logging
import requests
import uuid
import urllib
import sys
import time

class Test:
    def __init__(self):
        self.access_token = None
        self.room_id = None

    # Further setup
    def setup(self):
        print('Authenticating')

        authentication = requests.post('http://localhost:8080/_matrix/client/r0/login', json = {
            'type': 'm.login.password',
            'identifier': {
                'type': 'm.id.user',
                'user': 'user_1'
            },
            'password': 'user_1',
        }).json()
        print('Authentication %s' % authentication)
        self.access_token = 'Bearer %s' % authentication['access_token']


        # 1b. Creating the room.

        print('Creating public room')

        room_creation = requests.post('http://localhost:8080/_matrix/client/r0/createRoom', json = {
            'visibility': 'public',
        }, headers = {
            'Authorization': self.access_token
        }).json()
        print('Room creation %s' % room_creation)
        self.room_id = room_creation['room_id']

        print('Created room %s' % self.room_id)
        pass

    # 2. Starting actual test
    def test(self):
        quoted_room_id = urllib.parse.quote("%s" % self.room_id)
        print("Testing with room %s, access token %s" % (quoted_room_id, self.access_token))

        # A set of good events. They should be preserved in history.
        good_events = {}
        # A set of bad events. They should be redacted from history.
        bad_events = {}

        print('Sending raw text, it should pass')
        response = requests.put('http://localhost:8080/_matrix/client/r0/rooms/%s/send/m.room.message/%s' % (quoted_room_id, uuid.uuid1()),
            json = {
                'body': 'A text without any link',
                'format': 'org.matrix.custom.html',
                'formatted_body': 'A rich text without any link',
                'msgtype': 'm.text'
            },
            headers = {
                'Authorization': self.access_token
            }
        ).json()
        good_events[response['event_id']] = "raw text"


        print('Sending with good URLs, it should pass')
        response = requests.put('http://localhost:8080/_matrix/client/r0/rooms/%s/send/m.room.message/%s' % (quoted_room_id, uuid.uuid1()),
            json = {
                'body': 'A text with a good link to good.example.com',
                'format': 'org.matrix.custom.html',
                'formatted_body': 'A text without a good link to <a href="http://good.example.com">good.example.com</a>',
                'msgtype': 'm.text'
            },
            headers = {
                'Authorization': self.access_token
            }
        ).json()
        good_events[response['event_id']] = "good URL"

        print('Sending text with bad url in body, it should be rejected')
        response = requests.put('http://localhost:8080/_matrix/client/r0/rooms/%s/send/m.room.message/%s' % (quoted_room_id, uuid.uuid1()),
            json = {
                'body': 'A text a hidden link to evil.example.com',
                'format': 'org.matrix.custom.html',
                'formatted_body': 'A rich text without any link',
                'msgtype': 'm.text'
            },
            headers = {
                'Authorization': self.access_token
            }
        ).json()
        if response.get('event_id', None) is None:
            print('Message was rejected immediately')
        else:
            # Message may be redacted later
            bad_events[response['event_id']] = "bad URL in body"

        print('Sending text with bad url in formatted_body, it should be rejected')
        response = requests.put('http://localhost:8080/_matrix/client/r0/rooms/%s/send/m.room.message/%s' % (quoted_room_id, uuid.uuid1()),
            json = {
                'body': 'A text without any link',
                'format': 'org.matrix.custom.html',
                'formatted_body': 'A rich text without a hidden link to evil.example.com/1234',
                'msgtype': 'm.text'
            },
            headers = {
                'Authorization': self.access_token
            }
        ).json()
    
        if response.get('event_id', None) is None:
            print('Message was rejected immediately')
        else:
            # Message may be redacted later
            bad_events[response['event_id']] = "bad URL in formatted_body"

        print('Sending canary event, to ensure that all previous events have been flushed')
        response = requests.put('http://localhost:8080/_matrix/client/r0/rooms/%s/send/m.room.message/%s' % (quoted_room_id, uuid.uuid1()),
            json = {
                'body': 'A text without any link',
                'format': 'org.matrix.custom.html',
                'formatted_body': 'A rich text without any link',
                'msgtype': 'm.text'
            },
            headers = {
                'Authorization': self.access_token
            }
        ).json()
        canary_event = response['event_id']

        def item_generator(json_input, lookup_key):
            if isinstance(json_input, dict):
                for k, v in json_input.items():
                    if k == lookup_key:
                        yield v
                    else:
                        for child_val in item_generator(v, lookup_key):
                            yield child_val
            elif isinstance(json_input, list):
                for item in json_input:
                    for item_val in item_generator(item, lookup_key):
                        yield item_val

        # Wait until the canary has been treated.
        since = None
        while True:
            response = requests.get('http://localhost:8080/_matrix/client/r0/sync', json = {
                'since': since
            }, headers = {
                    'Authorization': self.access_token
                }
            ).json()
            since = response.get('since', None)
            found_canary = False
            for id in item_generator(response, 'event_id'):
                if id == canary_event:
                    found_canary = True
                    break
            if found_canary:
                break
            # Otherwise, wait a little.
            print("Apparently, not all events have been flushed, waiting a bit")
            time.sleep(0.5)

        # Now that we're sure that all events have been treated, re-download all events
        # and make sure that the good ones are all present and the bad ones are all either
        # absent or redacted away.
        print("Now checking that all good events have passed and all bad events have been rejected")
        since = None
        bad_events_found = set()
        while True:
            response = requests.get('http://localhost:8080/_matrix/client/r0/sync', json = {
                'since': since
            }, headers = {
                    'Authorization': self.access_token
                }
            ).json()
            since = response.get('since', None)
            found_canary = False

            # Ensure that all the good events are present
            for id in item_generator(response, 'event_id'):
                print("Encountering event id %s" % id)
                if id == canary_event:
                    found_canary = True
                maybe_good_event = good_events.get(id, None)
                if maybe_good_event != None:
                    print("Found good event: %s" % maybe_good_event)
                    del good_events[id]
                maybe_bad_event = bad_events.get(id, None)
                if maybe_bad_event != None:
                    print("Found bad event: %s" % maybe_bad_event)
                    bad_events_found.add(maybe_bad_event)

            # Ensure that all the bad events that are present are redacted away
            for id in item_generator(response, 'redacts'):
                print("Event %s has been redacted" % id)
                bad_events_found.remove(id)

            if found_canary:
                break
            # Otherwise, continue downloading.

        # By now, we should have found all the good events and none of the bad events.
        print("Let's see if there's any good event that we haven't found: %s" % good_events)
        assert len(good_events) == 0

        print("Let's see if there's any bad event that hasn't been redacted: %s" % bad_events_found)
        assert len(bad_events_found) == 0

        ## 3h. Upload benigne image. It should pass.
        # TODO

        ## 3i. Upload evil image. It should be blocked.
        # TODO

try:
    test = Test()
    test.setup()
    test.test()
except Exception as e:
    print("TEST FAILED: %s" % e)
    sys.exit(-1)
print("TEST SUCCEEDED")
sys.exit(1)