Feature: Face inspector and media serving
  As someone culling a shoot in Atelier
  I want to open any detected face, read its quality breakdown, jump to the original, and serve crops and images quickly
  So that I can judge a face in context and act on it without leaving the cull

  # The face inspector is a modal driven by openFaceModal(slug, fid) in
  # atelier/web/faces.js, mounted on #modal-face / #face-box in
  # atelier/web/index.html. It fetches GET /api/p/<slug>/face/<fid> and renders
  # the stored crop (GET /thumb/<fid>), detection confidence, overall quality,
  # and four quality bars (sharpness, eyes-open, smile, frontality), plus the
  # source filename and full path. Media is served by face_thumb, image_thumb,
  # full_image and (state-changing) fs_reveal in atelier/server.py. Mutating
  # requests require the per-process X-Atelier-Token (see _guard); reads do not.
  # The deep "Not this person" override semantics live in the people feature
  # file — here we only cover the modal interaction.

  Background:
    Given the Atelier server is running bound to 127.0.0.1
    And a project "demo" exists with indexed images and detected faces
    And the SPA holds the per-process token injected into index.html

  # ---------------------------------------------------------------------------
  # Face detail modal — opening and rendering
  # ---------------------------------------------------------------------------

  @ui @api
  Scenario: Opening a face loads its detail and shows the crop and metrics
    Given a face with id 42 belongs to image 7 at "/Users/me/Pictures/Trip/IMG_0420.JPG"
    When the user opens face 42
    Then the "#modal-face" modal becomes visible
    And a "GET /api/p/demo/face/42" request is sent
    And while it is in flight the box shows "Loading…"
    And on success the crop image is sourced from "/api/p/demo/thumb/42"
    And "Detection confidence" shows the face confidence as a percentage
    And "Overall quality" shows the quality score as a percentage
    And a quality bar is rendered for "Sharpness", "Eyes open", "Smile", and "Frontality"
    And the source filename "IMG_0420.JPG" is shown
    And the full path "/Users/me/Pictures/Trip/IMG_0420.JPG" is shown

  @api
  Scenario: The face detail JSON strips the embedding and thumbnail blobs
    Given a face row with id 42 carrying an "embedding" and a "thumbnail" column
    When a client sends "GET /api/p/demo/face/42"
    Then the response is the face row joined with its image path, width, height, and person display_name
    And the response JSON does not contain an "embedding" field
    And the response JSON does not contain a "thumbnail" field

  @ui
  Scenario Outline: Each quality bar fills proportionally and labels its percentage
    Given face 42 has "<metric>" equal to <value>
    When the modal renders
    Then the "<label>" bar fill width is "<width>"
    And its readout shows "<pct>"

    Examples:
      | metric         | label      | value | width | pct  |
      | face_sharpness | Sharpness  | 0.0   | 0%    | 0%   |
      | eye_open       | Eyes open  | 0.5   | 50%   | 50%  |
      | smile          | Smile      | 0.83  | 83%   | 83%  |
      | frontality     | Frontality | 1.0   | 100%  | 100% |

  @ui
  Scenario: A missing metric renders an empty bar and a dash readout
    Given face 42 has no "smile" value
    When the modal renders
    Then the "Smile" bar fill width is "0%"
    And its readout shows "–"

  @ui
  Scenario: The heading falls back when the face has no person display name
    Given face 42 has person_id 3 but no display_name
    When the modal renders
    Then the heading reads "Person 3"

  @ui
  Scenario: An ungrouped face is labelled Ungrouped
    Given face 42 has a negative person_id and no display_name
    When the modal renders
    Then the heading reads "Ungrouped"

  @ui @security
  Scenario: A person name with HTML is escaped before rendering
    Given face 42 belongs to a person named "<script>alert(1)</script>"
    When the modal renders
    Then the heading text is escaped and not executed as markup

  # ---------------------------------------------------------------------------
  # Face detail modal — error and close
  # ---------------------------------------------------------------------------

  @ui @api
  Scenario: An unknown face id returns 404 and the modal shows a friendly error
    When the user opens face 999999 which does not exist
    Then "GET /api/p/demo/face/999999" responds with status 404
    And the modal shows "Could not load this face."
    And the error view still offers a close button

  @ui
  Scenario: Closing the modal hides it
    Given the face detail modal is open for face 42
    When the user clicks the "×" close button
    Then "#modal-face" is hidden

  @ui
  Scenario: Clicking the modal backdrop closes it
    Given the face detail modal is open for face 42
    When the user clicks the backdrop outside "#face-box"
    Then "#modal-face" is hidden

  # ---------------------------------------------------------------------------
  # Face detail modal — actions
  # ---------------------------------------------------------------------------

  @ui
  Scenario: "Open original" opens the full image in the lightbox
    Given the face detail modal is open for face 42 on image 7
    When the user clicks "Open original"
    Then the lightbox opens showing "/api/p/demo/image/7"
    And the lightbox caption is the source filename

  @ui @api
  Scenario: "Reveal in Finder" succeeds
    Given the face detail modal is open for face 42 at an existing path
    When the user clicks "Reveal in Finder"
    Then a "POST /api/fs/reveal" is sent with {"path": "/Users/me/Pictures/Trip/IMG_0420.JPG"}
    And the response is {"ok": true}
    And a toast says "Revealed in Finder"

  @ui @api
  Scenario: "Reveal in Finder" reports failure as a sticky error toast
    Given the face detail modal is open for face 42
    When the user clicks "Reveal in Finder" and "POST /api/fs/reveal" returns {"ok": false}
    Then an error toast says "Could not reveal file"

  @ui
  Scenario: "Not this person" is only offered when the face belongs to a person
    Given face 42 has a negative person_id
    When the modal renders
    Then no "Not this person" button is shown

  @ui
  Scenario: "Not this person" offers split or remove-and-review
    Given the face detail modal is open for face 42 which belongs to person 3
    When the user clicks "Not this person"
    Then the action zone offers "Make a new person from this face"
    And it offers "Remove from this person"

  @ui @api
  Scenario: Making a new person from this face splits it out
    Given the "Not this person" choices are showing for face 42 of person 3
    When the user clicks "Make a new person from this face"
    Then a "POST /api/p/demo/persons/3/split" is sent with {"face_ids": [42]}
    And a toast says "Extracted into a new person"
    And the modal closes and a "atelier:people-changed" event fires

  @ui @api
  Scenario: Removing from this person then reviews visually-similar faces to also remove
    Given the "Not this person" choices are showing for face 42 of person 3
    When the user clicks "Remove from this person"
    Then a "POST /api/p/demo/faces/reject" is sent with {"face_ids": [42]}
    And "GET /api/p/demo/faces/42/similar?person=3&threshold=0.5" is fetched
    And when similar faces come back the user can tick more to remove
    And rejected faces persist as noise so they do not return on re-clustering

  @ui @api
  Scenario: Removing with no similar faces just confirms the single removal
    Given the user removed face 42 from person 3
    When the similar-faces lookup returns an empty list
    Then a toast says "Removed from person"
    And the modal closes and a "atelier:people-changed" event fires

  # ---------------------------------------------------------------------------
  # Face thumbnail — GET /thumb/<fid>
  # ---------------------------------------------------------------------------

  @api
  Scenario: A face thumbnail serves the stored JPEG crop
    Given face 42 has a stored "thumbnail" blob
    When a client sends "GET /api/p/demo/thumb/42"
    Then the response status is 200
    And the content type is "image/jpeg"
    And the body is the stored crop bytes

  @api
  Scenario Outline: A missing face or missing crop returns 404
    Given "<condition>"
    When a client sends "GET /api/p/demo/thumb/<fid>"
    Then the response status is 404

    Examples:
      | fid    | condition                                  |
      | 999999 | no face row with that id exists            |
      | 42     | the face exists but its thumbnail is NULL  |

  @api @security
  Scenario: Serving a face thumbnail needs no token
    When a client sends "GET /api/p/demo/thumb/42" with no token header
    Then the request is not blocked by the token guard

  # ---------------------------------------------------------------------------
  # Image thumbnail — GET /image_thumb/<iid>
  # ---------------------------------------------------------------------------

  @api
  Scenario: A precomputed image thumbnail is served from the stored blob and cached a day
    Given image 7 has a precomputed "thumbnail" blob
    When a client sends "GET /api/p/demo/image_thumb/7"
    Then the response status is 200
    And the content type is "image/jpeg"
    And the "Cache-Control" header is "public, max-age=86400"
    And the body is the stored thumbnail bytes

  @api
  Scenario: An older row with no stored thumbnail is decoded and resized on the fly
    Given image 7 has a NULL "thumbnail" but its original file exists on disk
    When a client sends "GET /api/p/demo/image_thumb/7"
    Then the original is decoded and resized to fit within 480x480 as JPEG quality 82
    And the response status is 200
    And the "Cache-Control" header is still "public, max-age=86400"

  @api
  Scenario Outline: The image thumbnail 404s when neither the blob nor the original exists
    Given "<condition>"
    When a client sends "GET /api/p/demo/image_thumb/<iid>"
    Then the response status is 404

    Examples:
      | iid    | condition                                                |
      | 999999 | no image row with that id exists                         |
      | 7      | the row has no thumbnail and its original file is gone   |

  # ---------------------------------------------------------------------------
  # Full image — GET /image/<iid>
  # ---------------------------------------------------------------------------

  @api
  Scenario: The full image serves the original file
    Given image 7 has an original at "/Users/me/Pictures/Trip/IMG_0420.JPG" that exists
    When a client sends "GET /api/p/demo/image/7"
    Then the response status is 200
    And the body is that original file

  @api
  Scenario Outline: The full image 404s when the row or the file is gone
    Given "<condition>"
    When a client sends "GET /api/p/demo/image/<iid>"
    Then the response status is 404

    Examples:
      | iid    | condition                                  |
      | 999999 | no image row with that id exists           |
      | 7      | the row exists but the original was moved  |

  # ---------------------------------------------------------------------------
  # Reveal in Finder — POST /api/fs/reveal
  # ---------------------------------------------------------------------------

  @api @security
  Scenario: Reveal runs "open -R" for an existing path on macOS
    Given the host platform is macOS
    And the path "/Users/me/Pictures/Trip/IMG_0420.JPG" exists
    And a client holds the current valid token
    When it sends "POST /api/fs/reveal" with {"path": "/Users/me/Pictures/Trip/IMG_0420.JPG"} and the valid token
    Then "open -R" is invoked on that path
    And the response is {"ok": true}

  @api
  Scenario: Reveal returns ok:false for a path that does not exist
    Given a client holds the current valid token
    When it sends "POST /api/fs/reveal" with {"path": "/nope/missing.jpg"} and the valid token
    Then no subprocess is launched
    And the response is {"ok": false}

  @api
  Scenario: Reveal returns ok:false off macOS where "open" is unavailable
    Given the host platform is not macOS
    And a client holds the current valid token
    When it sends "POST /api/fs/reveal" with an existing path and the valid token
    Then the "open" command cannot be found
    And the response is {"ok": false}

  @security @api
  Scenario: Reveal is a state-changing POST and requires the token
    When a client sends "POST /api/fs/reveal" with {"path": "/Users/me/x.jpg"} and no token header
    Then the response status is 403
    And the response description is "missing or invalid request token"
