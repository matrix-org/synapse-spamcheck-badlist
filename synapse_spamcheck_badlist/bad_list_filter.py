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

from linkify_it import LinkifyIt
from linkify_it.tlds import TLDS
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

        # Regexp for extracting info from mxc links.
        self._mxc_re = re.compile("mxc://(?P<server_name>.*)/(?P<media_id>.*)")

        # Linkifier, used to extract URLs from text.
        self._linkifier = (
            LinkifyIt()
            .tlds(TLDS)
            .tlds("onion", True)      # Add the `onion` tld
            .add("git:", "http:")     # Add the `git:` scheme with the same rules as `http:`
            .set({
                "fuzzy_ip": True,     # Attempt to recognize e.g. 192.168.0.1
                "fuzzy_link": True    # Attempt to recognize links without protocol
            })
        )
        self._scheme_re = re.compile("https?:/*|git:/*|ftp:/*")

        # One of:
        # - `None` if we haven't checked yet whether the database is present;
        # - `True` if we have checked and the database is present;
        # - `False` if we have checked and the database is absent.
        self._can_we_check_links = None
        self._can_we_check_md5 = None

    async def can_we_check_links(self) -> bool:
        """
            Check whether the links database exists, caching the result.
        """
        if self._can_we_check_links is not None:
            return self._can_we_check_links
        if self._links_table is None:
            self._can_we_check_links = False
            return False
        try:
            def interaction(db):
                db.execute("SELECT url FROM %s LIMIT 1" % self._links_table)
            await self._api.run_db_interaction("Check whether we can check links", interaction)
            self._can_we_check_links = True
            logger.info("We can check links!")
        except Exception as e:
            logger.warn("We CANNOT check links! %s" % e)
            self._can_we_check_links = False
        return self._can_we_check_links
        
    async def can_we_check_md5(self) -> bool:
        """
            Check whether the MD5 database exists, caching the result.
        """
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
        if await self.can_we_check_links():
            # Check for links in text, both unformatted and formatted.
            #
            # We always lower-case the url, as the IWF database is lowercase.
            for text in [content.get("body", ""), content.get("formatted_body", "")]:
                # Run a first, faster test.
                if not self._linkifier.test(text):
                    continue
                # Now run the slower test, if necessary, using results cached from the faster test.
                for match in self._linkifier.match(text) or []:
                    link = re.sub(self._scheme_re, "", match.url.lower())
                    is_bad_link = await self._api.run_db_interaction("Check link against evil db", _db_is_bad_link, self._links_table, link)
                    if is_bad_link:
                        logger.info("Rejected bad link")
                        return True

        # If it's a file, download content, extract hash.
        if content.get("msgtype", "") in ["m.file", "m.image", "m.audio"]:
            if not await self.can_we_check_md5():
                return False

            match = self._mxc_re.match(content.get("url", ""))
            if match != None:
                server_name = match.group('server_name')
                media_id = match.group('media_id')
                response = None
                try:
                    url = "%s/_matrix/media/r0/download/%s/%s" % (
                            self._base_url,
                            urlquote(server_name),
                            urlquote(media_id)
                    )
                    response = await self._api.http_client.request("GET", url)
                except Exception as e:
                    # In case of timeout or error, there's nothing we can do.
                    # Let's not take the risk of blocking valid contents.
                    logger.warn("Could not download media: '%s', assuming it's not spam." % e)
                    return False
                if response.code == 429:
                    logger.warn("We were rate-limited, assuming it's not spam.")
                    return False

                md5 = hashlib.md5()
                await response.collect(lambda batch: md5.update(batch))
                is_bad_upload = await self._api.run_db_interaction("Check upload against evil db", _db_is_bad_upload, self._md5_table, md5.hexdigest())
                if is_bad_upload:
                    logger.info("Rejected bad upload")
                    return True

        # Not spam
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


def _db_is_bad_link(db, table, link):
    """
    Search if any url in the database is a prefix of `link`.
    `link` MUST be normalized by `_link_for_search`.
    """
    # Note: As per IWF guidelines, we're looking for *prefixes*. This might
    # be slow. We're quickly going to have 1M+ links, so we need to find out
    # whether this slows things down.
    #
    # 1. Find the closest url.
    db.execute(("SELECT url FROM %s WHERE url <= ? ORDER BY url DESC LIMIT 1" % table), (link, ))
    row = db.fetchone()
    if not row:
        logger.info("No match in %s for link %s " % (table, link))
        return False

    # 2. Check whether it's actually a prefix.
    logger.info("Located potential prefix %s" % row[0])
    return link.startswith(row[0])

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