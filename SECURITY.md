# Security

chartarr stores your Lidarr API key in `~/.config/chartarr/config.json`,
created readable only by you. The key is sent to your Lidarr instance in the
`X-Api-Key` header and nowhere else; chartarr talks to MusicBrainz without
credentials of any kind.

To report a vulnerability, use GitHub's private reporting on this repository
(Security → Report a vulnerability) rather than opening an issue.
