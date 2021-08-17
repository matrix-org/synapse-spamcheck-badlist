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
import re
import time

import ahocorasick
from ahocorasick import Automaton
from prometheus_client import Counter, Histogram
from twisted.internet import defer, reactor
from twisted.internet.threads import deferToThread

from synapse.logging import context
from synapse.metrics.background_process_metrics import run_as_background_process

logger = logging.getLogger(__name__)

link_check_performance = Histogram(
    "synapse_spamcheck_badlist_link_check_performance",
    "Performance of link checking, in seconds. This operation is in the critical path between a message being sent and that message being delivered to other members.",
)
badlist_md5_found = Counter(
    "synapse_spamcheck_badlist_md5_found",
    "Number of bad uploads found by md5 check",
)
badlist_link_found = Counter(
    "synapse_spamcheck_badlist_link_found",
    "Number of bad uploads found by link check",
)


class BadListFilter(object):
    """
    A simple spam checker module for Synapse, designed to block upload
    of identified child sexual abuse imagery and links to identified
    child sexual abuse websites.

    This filter requires:
    - a database of links of identified child sexual abuse websites
        (as published by e.g. the IWF);
    - a database of MD5s of identified child sexual abuse imagery
        (as published by e.g. the IWF).

    This filter assumes that the list of links is small enough that
    it can fit in memory. This is consistent with what the IWF provides
    (the list is a few thousands links longs).

    The filter:
    - rejects any message containing a link that matches the database;
    - rejects any upload containing a file that matches the database.
    """

    def __init__(self, config, api):
        # The plug-in API.
        self._api = api

        # The table containing links. Configured in homeserver.yaml
        # as `spam_checker.config.links_table`.
        self._links_table = config["links_table"]
        logger.info("Using links table %s", self._links_table)

        # The table containing md5 hashes. Configured in homeserver.yaml
        # as `spam_checker.config.links_table`.
        self._md5_table = config["md5_table"]
        logger.info("Using md5 table %s", self._md5_table)

        # How often we should check for updates in the database.
        # Configured in homeserver.yaml
        # as `spam_checker.config.pull_from_db_every_sec`.
        pull_from_db_every_sec = int(config["pull_from_db_every_sec"])
        logger.info("Rechecking database every %s seconds", pull_from_db_every_sec)

        # A ahocorasick.Automaton used to recognize bad links.
        self._link_automaton = None

        # Start the loop to update links.
        api.looping_background_call(
            f=self._update_links_automaton,
            msec=pull_from_db_every_sec * 1000,
            desc="Background update list of bad links",
        )

        # As soon as we can, run the first fetch.
        # Note that we have no guarantee that this is finished
        # by the time we receive the first message, so we need
        # a fallback in `_get_links_automaton()`.
        reactor.callWhenRunning(
            lambda: defer.ensureDeferred(
                run_as_background_process(func=self._update_links_automaton, desc="Background initial pull list of bad links")
            )
        )

    async def _update_links_automaton(self):
        """
        Fetch the latest version of the links from the table, build an automaton.
        """
        logger.info(
            "_update_links_automaton: fetching links from table %s", self._links_table,
        )
        try:
            links = await self._api.run_db_interaction(
                "Fetch links from the table", _db_fetch_links, self._links_table
            )
            logger.info("_update_links_automaton: we received %d links", len(links))
            new_link_automaton = Automaton(ahocorasick.STORE_LENGTH)
            for link in links:
                new_link_automaton.add_word(link)
            await deferToThread(new_link_automaton.make_automaton)
            self._link_automaton = new_link_automaton
        except Exception as e:
            logger.exception("_update_links_automaton: could not update")
            raise e

    async def _get_link_automaton(self) -> Automaton:
        """
        Get the automaton used to recognize bad links.
        The automaton is updated every `self._pull_from_db_every_sec` seconds.
        """
        if self._link_automaton is None:
            # In the very unlikely case that the first run of _update_links_automaton()
            # hasn't completed yet, we need to replicate it here and block the message
            # until it is complete.
            # In the worst case scenario, this will happen exactly once per process.
            await self._update_links_automaton()
        return self._link_automaton

    async def check_event_for_spam(self, event) -> bool:
        if event["type"] != "m.room.message":
            # We only filter messages.
            return False

        content = event.get("content", {})

        # Look for links in text content.
        # Note that all messages can have a text content, even files (as part of the description), etc.
        with link_check_performance.time():
            automaton = await self._get_link_automaton()

            # Check for links in text, both unformatted and formatted.
            #
            # We always lower-case the url, as the IWF database is lowercase.
            for text in [
                content.get("body"),
                content.get("formatted_body"),
            ]:
                if not isinstance(text, str):
                    continue

                for _ in automaton.iter(text):
                    logger.info("Rejected bad link")
                    badlist_link_found.inc()
                    return True

        # Not spam
        return False

    async def check_media_file_for_spam(self, file_wrapper, file_info):
        # Compute MD5 of file.
        hasher = hashlib.md5()
        await file_wrapper.write_chunks_to(hasher.update)

        hex_digest = hasher.hexdigest()

        # Check if it shows up in the db.
        if await self._api.run_db_interaction(
            "Check whether this md5 shows up in the database",
            _db_is_bad_upload,
            self._md5_table,
            hex_digest,
        ):
            logger.info("Rejected bad media file")
            badlist_md5_found.inc()
            return True
        return False

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
    db.execute(("SELECT md5 FROM %s WHERE md5 = ?" % table), (md5,))
    row = db.fetchone()
    if not row:
        return False
    return True


# Run doctests
if __name__ == "__main__":
    import doctest

    doctest.testmod()
