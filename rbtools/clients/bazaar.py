import os
import re
import sys

from rbtools.clients import SCMClient, RepositoryInfo
from rbtools.utils.checks import check_install
from rbtools.utils.process import die, execute
from bzrlib import workingtree

class BazaarClient(SCMClient):
    """
    Bazaar client wrapper that fetches repository information and generates
    compatible diffs.

    The :class:`RepositoryInfo` object reports whether the repository supports
    parent diffs (every branch with a parent supports them).

    """

    BRANCH_REGEX = r'\w*(repository branch|branch root): (?P<branch_path>.+)$'
    """
    Regular expression that matches the path to the current branch.

    For branches with shared repositories, Bazaar reports
    "repository branch: /foo", but for standalone branches it reports
    "branch root: /foo".

    """
    def __init__(self, **kwargs):
        super(BazaarClient, self).__init__(**kwargs)

    def get_repository_info(self):
        """
        Find out information about the current Bazaar branch (if any) and return
        it.

        """
        if not check_install("bzr help"):
            return None

        if self.options.repository_url:
            return RepositoryInfo(
                path=self.options.repository_url,
                base_path="/",    # Diffs are always relative to the root.
                supports_parent_diffs=True,
            )

        branch = None

        for location in ['submit_branch', 'parent_location']:
            branch = self._get_config(location)
            if branch is not None:
                break

        if branch is None:
            return None

        return RepositoryInfo(
            path=branch,
            base_path="/",    # Diffs are always relative to the root.
            supports_parent_diffs=True,
        )

    def scan_for_server(self, repository_info):
        """
        Return server URL, look for a 'reviewboard_url' config entry.
        """
        server_url = self._get_config('reviewboard_url')
        if server_url is not None:
            return server_url

        return SCMClient.scan_for_server(self, repository_info)

    def _get_config(self, name):
        """
        Return configuration value for name, or None if not available.
        """
        value = execute(['bzr', 'config', name], extra_ignore_errors=(3,))
        if 'ERROR: The "' + name + '" configuration option does not exist.' in value:
            return None
        return value.rstrip()

    def diff(self, files):
        """
        Return the diff of this branch with respect to its parent and set
        the summary and description is required.

        """
        files = files or []

        if self.options.parent_branch:
            revision_range = "ancestor:%s.." % self.options.parent_branch
        else:
            revision_range = "submit:.."

        # Getting the diff for the changes in the current branch:
        diff = self._get_range_diff(revision_range, files)
        self._set_summary("-1")
        self._set_description(revision_range)

        return (diff, None)

    def diff_between_revisions(self, revision_range, files, repository_info):
        """
        Return the diff for the two revisions in ``revision_range`` and set
        the summary and description is required.

        """
        diff = self._get_range_diff(revision_range, files)

        # Revision ranges in Bazaar and separated with dots, not colons:
        last_revision = revision_range.split("..")[1]
        self._set_summary(last_revision)
        self._set_description(revision_range)

        return diff

    def _get_range_diff(self, revision_range, files):
        """
        Return the diff for the two revisions in ``revision_range``.

        """
        diff_cmd = ["bzr", "dif", "-q", "-r", revision_range]
        print diff_cmd + files
        diff = execute(
            diff_cmd + files,
            ignore_errors=True,
            )
        diff = diff or None

        return diff

    def _set_summary(self, revision):
        """
        Set the summary to the message of ``revision`` if asked to guess it.

        """
        if self.options.guess_summary and not self.options.summary:
            self.options.summary = self._extract_summary(revision)

    def _set_description(self, revision_range=None):
        """
        Set the description to the changelog of ``revision_range`` if asked to
        guess it.

        """
        if self.options.guess_description and not self.options.description:
            self.options.description = self._extract_description(revision_range)

    def _extract_summary(self, revision):
        """Return the commit message for ``revision``."""
        # `bzr log --line' returns the log in the format:
        #   {revision-number}: {committer-name} {commit-date} {commit-message}
        # So we should ignore everything after the date (YYYY-MM-DD).
        log_message = execute(["bzr", "log", "-r", revision, "--line"]).rstrip()
        log_message_match = re.search(r"\d{4}-\d{2}-\d{2}", log_message)
        truncated_characters = log_message_match.end() + 1

        summary = log_message[truncated_characters:]

        debug('Summary: %s' % summary)

        return summary

    def _extract_description(self, revision_range=None):
        command = ["bzr"]

        # If there is no revision range specified, that means we need the logs
        # of all the outgoing changes:
        if revision_range:
            command.extend(["log", '-n1', '--gnu-changelog',
                            '--exclude-common-ancestry',
                            "-r", revision_range])
        else:
            if self.options.parent_branch:
                branch = self.options.parent_branch
            else:
                branch = ':submit'
            command.extend(["missing", "-q", "--mine-only", '--gnu-changelog', branch])

        # We want to use the "short" output format, where all the logs are
        # separated with hyphens:
        command.append("--short")

        changelog = execute(command, ignore_errors=True).rstrip()

        debug('Changelog:\n%s' % changelog)

        return changelog
