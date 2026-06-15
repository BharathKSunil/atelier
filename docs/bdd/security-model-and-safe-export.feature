Feature: Security model and safe export
  As the single local user of Atelier
  I want the API to answer only to my own machine, reject forged requests, and confine exports to safe folders
  So that a drive-by web page or a malicious request cannot reach my photos or write files anywhere on disk

  # Atelier is loopback-only and unauthenticated by design (one local user). Its
  # defenses are: a per-process CSRF token injected into index.html and required on
  # every state-changing request; a Host/Origin allowlist; and export-destination
  # containment. The native folder picker is macOS-only and guarded against
  # AppleScript injection. See atelier/server.py (_guard, _safe_dest, _allowed_roots,
  # export routes) and atelier/fsdialog.py.

  Background:
    Given the Atelier server is running bound to 127.0.0.1
    And a per-process token was generated at startup and injected into index.html
    And the loopback hosts allowlist is "127.0.0.1", "localhost", "::1", and empty host
    And a project "demo" exists

  # ---------------------------------------------------------------------------
  # Loopback binding & host allowlist
  # ---------------------------------------------------------------------------

  @security @api
  Scenario: The server binds to loopback only
    When the server process starts
    Then it listens on host "127.0.0.1"
    And it is never exposed beyond the loopback interface

  @security @api
  Scenario: A request with a non-local Host header is rejected
    When a client sends "GET /api/projects" with header "Host: 192.168.1.50:5050"
    Then the response status is 403
    And the response description is "non-local host"

  @security @api
  Scenario Outline: Requests whose Host resolves to a loopback name are admitted by the host guard
    When a client sends "GET /api/projects" with header "Host: <host>"
    Then the host guard does not reject the request
    And the response status is 200

    Examples:
      | host            |
      | 127.0.0.1:5050  |
      | localhost:5050  |
      | [::1]:5050      |

  # ---------------------------------------------------------------------------
  # Cross-origin protection
  # ---------------------------------------------------------------------------

  @security @api
  Scenario: A cross-origin POST is blocked even with a valid token
    Given a client holds the current valid token
    When it sends "POST /api/projects" with header "Origin: http://evil.example"
    Then the response status is 403
    And the response description is "cross-origin request blocked"

  @security @api
  Scenario: A same-origin request carrying a loopback Origin is allowed through the origin guard
    Given a client holds the current valid token
    When it sends "POST /api/projects" with header "Origin: http://localhost:5050" and a valid body
    Then the origin guard does not reject the request

  @security @api
  Scenario: A request with no Origin header passes the origin guard
    When a GET request is sent with no Origin header
    Then the origin guard does not reject the request
    And the response status is 200

  # ---------------------------------------------------------------------------
  # CSRF token on state-changing requests
  # ---------------------------------------------------------------------------

  @security @api
  Scenario: The token is injected into the served index.html
    When a client requests "GET /"
    Then the HTML contains a "<script>window.ATELIER_TOKEN=...</script>" tag
    And the SPA reads that token and sends it as "X-Atelier-Token" on mutating fetches

  @security @api
  Scenario: A mutating request without the token is forbidden
    When a client sends "POST /api/projects" with body {"name":"x","folder":"/nope"} and no token header
    Then the response status is 403
    And the response description is "missing or invalid request token"

  @security @api
  Scenario: A mutating request with a wrong token is forbidden
    When a client sends "POST /api/projects" with header "X-Atelier-Token: not-the-real-token"
    Then the response status is 403
    And the response description is "missing or invalid request token"

  @security @api
  Scenario: A mutating request with the correct token passes the guard and reaches the handler
    Given a client holds the current valid token
    When it sends "POST /api/projects" with body {"name":"x","folder":"/nope"} and the valid token
    Then the request passes the security guard
    And the response status is 400
    And the rejection comes from the handler validating the folder, not from the guard

  @security @api
  Scenario Outline: Every state-changing HTTP method requires the token
    When a client sends a "<method>" request to a mutating endpoint without the token
    Then the response status is 403
    And the response description is "missing or invalid request token"

    Examples:
      | method |
      | POST   |
      | PUT    |
      | DELETE |
      | PATCH  |

  @security @api
  Scenario: GET requests do not require a token
    When a client sends "GET /api/projects" with no token header
    Then the response status is 200
    And the body is the JSON list of projects

  @security @api
  Scenario: Reading media and thumbnails needs no token
    Given the project "demo" has an image with id 1
    When a client sends "GET /api/p/demo/image_thumb/1" with no token header
    Then the request is not blocked by the token guard

  @security @api
  Scenario: The token is compared in constant time
    When the supplied "X-Atelier-Token" is checked against the per-process token
    Then the comparison uses a constant-time digest comparison
    So that the token cannot be discovered by timing attack

  # ---------------------------------------------------------------------------
  # Export destination containment
  # ---------------------------------------------------------------------------

  @security @api
  Scenario: An export destination outside the allowed roots is rejected
    Given a client holds the current valid token
    When it sends "POST /api/p/demo/persons/0/export" with body {"dest":"/etc/atelier-pwn"} and the valid token
    Then the response status is 400
    And the response body is {"ok": false, "msg": "choose a valid destination folder"}
    And no files are written to "/etc"

  @security @api
  Scenario: An export destination under an allowed root is accepted
    Given a client holds the current valid token
    And the destination "<projects_dir>/out" lies under the projects directory
    When it sends "POST /api/p/demo/persons/0/export" with that destination and the valid token
    Then the response status is 200
    And the response body has "ok" true
    And the destination folder is created if it did not exist

  @security @api
  Scenario Outline: Destination containment honours the allowed-root set
    Given a client holds the current valid token
    When it requests an export to "<dest>"
    Then the request is "<outcome>"

    Examples:
      | dest                          | outcome           |
      | ~/Pictures/atelier-out        | accepted (200)    |
      | <projects_dir>/combined       | accepted (200)    |
      | /tmp/atelier-out              | accepted (200)    |
      | /Volumes/SSD/exports          | accepted (200)    |
      | /etc/atelier-pwn              | rejected (400)    |
      | /usr/local/bin                | rejected (400)    |
      |                               | rejected (400)    |

  @security @api
  Scenario: A traversal path that resolves outside an allowed root is rejected
    Given a client holds the current valid token
    When it requests an export to "~/../../etc/passwd-dir"
    Then the destination is resolved with realpath before the root check
    And because the real path escapes every allowed root the response status is 400

  @security @api
  Scenario: A union export across multiple people still enforces containment
    Given the project "demo" has person 1 in images 1 and 2, and person 2 in image 3
    And a client holds the current valid token
    When it sends "POST /api/p/demo/persons/export" with {"ids":[1,2],"dest":"<projects_dir>/combined"} and the valid token
    Then the response status is 200
    And exactly 3 deduplicated originals are copied
    When it then requests the same export to "/etc/x"
    Then the response status is 400
    And the response body is {"ok": false, "msg": "choose a valid destination folder"}

  @security @api
  Scenario: Print and single-image exports fall back to a safe default destination
    Given a client holds the current valid token
    When it sends "POST /api/p/demo/prints/export" with no "dest" in the body
    Then the destination defaults to "./print_exports/demo"
    And that default is still resolved and confined to an allowed root before any copy

  # ---------------------------------------------------------------------------
  # Native folder picker — macOS only, injection-guarded
  # ---------------------------------------------------------------------------

  @security @ui
  Scenario: The native folder picker opens on macOS
    Given the host platform is macOS and "osascript" is available
    When the user clicks "Choose folder" and the picker returns "/Users/me/Pictures/Trip"
    Then "POST /api/fs/choose" responds {"ok": true, "path": "/Users/me/Pictures/Trip", "exists": true}

  @security @ui
  Scenario: Cancelling the native picker yields a non-error cancelled response
    Given the host platform is macOS and the picker is available
    When the user opens the picker and presses Cancel
    Then "POST /api/fs/choose" responds with status 200 and {"ok": false, "msg": "cancelled", "unavailable": false}
    And the UI takes no further action

  @security @ui
  Scenario Outline: A default location containing AppleScript-injection characters is never interpolated
    Given the host platform is macOS
    And a default path "<default>" containing a "<char>"
    When "POST /api/fs/choose" is called with that default
    Then the default location is omitted from the AppleScript command
    And no shell or AppleScript escape can break out of the string literal

    Examples:
      | char           | default                          |
      | double quote   | /Users/me/a"b                    |
      | backslash      | /Users/me/a\b                    |
      | newline        | /Users/me/a\nb                   |
      | carriage ret   | /Users/me/a\rb                   |

  @security @ui
  Scenario: A clean default location is passed to the native dialog
    Given the host platform is macOS
    And a real existing folder "/Users/me/Pictures" with no quote, backslash, or newline characters
    When the picker is opened with that default
    Then the AppleScript includes 'default location POSIX file "/Users/me/Pictures"'

  @security @ui
  Scenario: Off macOS the picker is unavailable and the UI falls back to typing a path
    Given the host platform is not macOS, or "osascript" is not on PATH
    When the user clicks "Choose folder"
    Then "POST /api/fs/choose" responds with status 200 and {"ok": false, "unavailable": true}
    And the message is "native folder picker is macOS-only — type or paste the folder path"
    And the UI shows that message and focuses the folder text field so the user can paste a path
    And the typed path is still confined to the allowed export roots when it is used
