# Copyright 2020 The Matrix.org Foundation C.I.C.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import hashlib
import logging
import time
import re

import ahocorasick
from ahocorasick import Automaton
from prometheus_client import Histogram
from urllib.parse import quote as urlquote

logger = logging.getLogger(__name__)

class BadListFilter(object):
    """
    A simple spam checker module for Synapse, designed to block upload of identified child sexual abuse
    imagery and links to identified child sexual abuse websites.

    This filter requires:
    - a database of links of identified child sexual abuse websites (as published by e.g. the IWF);
    - a database of MD5s of identified child sexual abuse imagery (as published by e.g. the IWF).

    The filter:
    - rejects any message containing a link that matches the database;
    - rejects any upload containing a file that matches the database.
    """
    def __init__(self, config, api):
        # The plug-in API.
        self._api = api

        # The table containing links. Configured in homeserver.yaml, spam_checker.config.links_table.
        self._links_table = config["links_table"]
        logger.info("Using links table %s" % self._links_table)

        # The table containing md5 hashes. Configured in homeserver.yaml, spam_checker.config.links_table.
        self._md5_table = config["md5_table"]
        logger.info("Using md5 table %s" % self._md5_table)

        # The base url for this server. Configured in homeserver.yaml, spam_checker.config.base_url.
        self._base_url = config["base_url"]
        logger.info("Using base url %s" % self._base_url)

        # How often we should check for updates in the database.
        self._pull_from_db_every_sec = int(config["pull_from_db_every_sec"])
        logger.info("Rechecking database every %s seconds", self._pull_from_db_every_sec)

        # Regexp for extracting info from mxc links.
        self._mxc_re = re.compile("mxc://(?P<server_name>.*)/(?P<media_id>.*)")

        # A ahocorasick.Automaton used to recognize bad links.
        self._link_automaton = None

        self._link_check_performance = Histogram('synapse_spamcheck_badlist_link_check_performance', 'Performance of link checking, in seconds. This operation is in the critical path between a message being sent and that message being delivered to other members.')
        self._md5_check_performance = Histogram('synapse_spamcheck_badlist_md5_check_performance', 'Performance of md5 checking, in seconds. This operation is in the critical path between a message being sent and that message being delivered to other members.')

        # One of:
        # - `None` if we haven't checked yet whether the database is present;
        # - `True` if we have checked and the database is present;
        # - `False` if we have checked and the database is absent.
        self._can_we_check_links = None
        self._can_we_check_md5 = None

        # Timestamp for the latest pull from the links table (or attempt to pull,
        # if the links table was empty), as returned by `time.time()`.
        self._last_checked_links = None
        self._last_checked_md5 = None

    async def can_we_check_links(self) -> bool:
        """
            Check whether the links database exists, caching the result.
        """
        now = time.time()
        if (self._last_checked_links is None) or (self._last_checked_links + self._pull_from_db_every_sec >= now):
            # Force a recheck of the links.
            logger.info("can_we_check_links: Forcing a recheck of the links")
            self._can_we_check_links = None
            self._last_checked_links = now
        if self._can_we_check_links is not None:
            return self._can_we_check_links
        if self._links_table is None:
            logger.info("can_we_check_links: No table")
            self._can_we_check_links = False
            return False
        try:
            logger.info("can_we_check_links: fetching links from table %s" % self._links_table)
            links = await self._api.run_db_interaction("Fetch links from the table", _db_fetch_links, self._links_table)
            logger.info("can_we_check_links: we received %s links" % len(links))
            self._can_we_check_links = True
            self._link_automaton = Automaton(ahocorasick.STORE_LENGTH)
            for link in links:
                self._link_automaton.add_word(link)
            self._link_automaton.make_automaton()
            logger.info("We can check links!")
        except Exception as e:
            logger.warn("We CANNOT check links! %s" % e)
            self._can_we_check_links = False
        return self._can_we_check_links
        
    async def can_we_check_md5(self) -> bool:
        """
            Check whether the MD5 database exists, caching the result.
        """
        now = time.time()
        if (self._last_checked_md5 is None) or (self._last_checked_md5 + self._pull_from_db_every_sec >= now):
            # Force a recheck of the table.
            self._can_we_check_md5 = None
            self._last_checked_md5 = now
        if self._can_we_check_md5 is not None:
            return self._can_we_check_md5
        if self._md5_table is None:
            self._can_we_check_md5 = False
            return False
        try:
            def interaction(db):
                db.execute("SELECT md5 FROM %s LIMIT 1" % self._md5_table)
            await self._api.run_db_interaction("Check whether we can check md5", interaction)
            self._can_we_check_md5 = True
            logger.info("We can check md5!")
        except:
            logger.warn("We CANNOT check md5!")
            self._can_we_check_md5 = False
        return self._can_we_check_md5

    async def check_event_for_spam(self, event) -> bool:
        if event["type"] != "m.room.message":
            # We only filter messages.
            return False

        content = event.get("content", {})

        # Look for links in text content.
        # Note that all messages can have a text content, even files (as part of the description), etc.
        with self._link_check_performance.time():
            if await self.can_we_check_links():
                # Check for links in text, both unformatted and formatted.
                #
                # We always lower-case the url, as the IWF database is lowercase.
                for text in [content.get("body", ""), content.get("formatted_body", "")]:
                    for _ in self._link_automaton.iter(text):
                        logger.info("Rejected bad link")
                        return True

        # Not spam
        return False

    async def check_media_file_for_spam(self, file_wrapper, file_info):
        if await self.can_we_check_md5():
            logger.info("Checking media file")
            # Compute MD5 of file.
            hasher = hashlib.md5()
            await file_wrapper.write_chunks_to(hasher.update)

            hex_digest = hasher.hexdigest()

            # Check if it shows up in the db.
            if await self._api.run_db_interaction("Check whether this md5 shows up in the database", _db_is_bad_upload, self._md5_table, hex_digest):
                logger.info("Rejected bad media file")
                return True

        return False  # allow all media

    def check_username_for_spam(self, user_profile):
        return False  # allow all usernames

    def user_may_invite(
        self, inviter_userid: str, invitee_userid: str, room_id: str
    ) -> bool:
        # Allow all invites
        return True

    def user_may_create_room(self, userid: str) -> bool:
        # Allow all room creations
        return True

    def user_may_create_room_alias(self, userid: str, room_alias: str) -> bool:
        # Allow all room aliases
        return True

    def user_may_publish_room(self, userid: str, room_id: str) -> bool:
        # Allow publishing all rooms
        return True

    @staticmethod
    def parse_config(config):
        # No parsing needed
        return config


def _db_fetch_links(db, table):
    """
    Pull the list of links from the database.
    """
    db.execute("SELECT url FROM %s" % table)
    return [row[0] for row in db]

def _db_is_bad_upload(db, table, md5):
    """
    Search if the md5 appears in the database.
    """
    db.execute(("SELECT md5 FROM %s WHERE md5 = ?" % table), (md5, ))
    row = db.fetchone()
    if not row:
        return False
    return True


# Run doctests
if __name__ == "__main__":
    import doctest
    doctest.testmod()
