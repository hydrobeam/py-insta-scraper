import json
import urllib.parse
from dataclasses import dataclass


@dataclass
class EndpointsClass:
    BASE_URL: str = "https://www.instagram.com"
    ACCOUNT_MEDIAS: str = "https://www.instagram.com/graphql/query/?query_hash=e769aa130647d2354c40ea6a439bfc08&variables={variables}"
    ACCOUNT_JSON_INFO: str = "https://www.instagram.com/{username}/?__a=1&__d=dis"

    def account_json(self, username: str) -> str:
        """Generate an endpoint to get JSON info about a user

        Parameters
        ----------
        username : str
            The user to be queried

        Returns
        -------
        str
            An endpoint that can be used to access JSON info about ``username``
        """

        return self.ACCOUNT_JSON_INFO.replace(
            "{username}", urllib.parse.quote(username)
        )

    def account_medias(self, user_id: str, after: str = "", count: int = 50) -> str:
        """Generates an endpoint to access the posts of a user

        ``count`` is capped at 50 for a single view.

        Parameters
        ----------
        user_id : int
            The id of the user to query
        after : str
            The ``end_cursor`` value from previous calls of the user's feed
        count : int
            The number of posts to view, capped at 50 for one call
        """

        vars_dict = {"id": user_id, "first": count, "after": after}

        return self.ACCOUNT_MEDIAS.replace(
            "{variables}", urllib.parse.quote_plus(json.dumps(vars_dict))
        )


Endpoints = EndpointsClass()
