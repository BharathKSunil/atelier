Feature: Review / cull — step through bursts and choose keepers
  As a photographer culling a shoot
  I want to step through each burst, see the recommended frame, tag picks by criterion,
  and star the frames I want to print
  So that I end up with a clean Print list without losing my manual choices when the pipeline reruns.

  Background:
    Given a project "wedding" exists with an indexed, scored library
    And the pipeline has grouped images into series (bursts)
    And I am on the Review / cull view for project "wedding"

  # ---------------------------------------------------------------------------
  # Which bursts are reviewable
  # ---------------------------------------------------------------------------

  @api
  Scenario: Only multi-frame bursts are listed for review
    When the client requests GET "/api/p/wedding/series?offset=0&limit=200"
    Then the response status is 200
    And every returned item has a "frame_count" greater than 1
    And no singleton series (frame_count of 1) is included
    And the items are ordered chronologically by "time_start" (sort=time is the default)
    And each item carries "time_start", "time_end" and "reviewed_at"

  @api
  Scenario Outline: Bursts can be re-sorted from the Review bar
    When the client requests GET "/api/p/wedding/series?sort=<sort>"
    Then the response status is 200
    And the bursts are ordered by "<ordered_by>"

    Examples:
      | sort  | ordered_by              |
      | time  | time_start ascending    |
      | count | frame_count descending  |
      | score | best_score descending   |

  @api @persistence
  Scenario: The series list is paged and the first burst renders after page one
    Given there are 250 multi-frame bursts
    When the Review view mounts
    Then it requests GET "/api/p/wedding/series?sort=time&offset=0&limit=200"
    And the first burst renders as soon as page one arrives — it does not block on every page
    And it keeps paging "offset=200&limit=200" in the background
    And the burst counter denominator uses the server "total", not the pages loaded so far

  @ui
  Scenario: Empty state when there are no multi-frame bursts
    Given project "wedding" has no series with frame_count greater than 1
    When the Review view mounts
    Then the stage shows "No multi-frame bursts to review."
    And the filmstrip is empty
    And the burst counter shows "—"
    And no image request is made

  # ---------------------------------------------------------------------------
  # The recommended frame + the stage
  # ---------------------------------------------------------------------------

  @ui
  Scenario: The recommended group frame is the highlighted hero on load
    Given the current burst has a "group" pick for image 42
    When the burst loads
    Then the stage shows image 42
    And the filmstrip thumbnail for image 42 is marked as current
    And the burst counter reads "Burst 1 of N · <frames> frames"

  @ui
  Scenario: Hero falls back to the top-scored frame when there is no group pick
    Given the current burst has no "group" pick
    And the burst's frames are returned ordered by print_score descending
    When the burst loads
    Then the stage shows the first (highest print_score) frame

  @api
  Scenario: Burst frames come back in capture sequence
    When the client requests GET "/api/p/wedding/series/7/images"
    Then the response status is 200
    And the frames are ordered by capture time ("taken_at", then "sub_sec", then id)
    And each frame carries an "is_print" flag reflecting the Print list
    And each frame carries "taken_at", "face_count", "global_sharpness" and "exposure_score"

  # ---------------------------------------------------------------------------
  # Multi-criteria picks — auto-derived, manual override
  # ---------------------------------------------------------------------------

  @api
  Scenario: Picks are auto-derived from per-criterion scores when no manual pick exists
    Given burst 7 has no manual picks
    When the client requests GET "/api/p/wedding/series/7/picks"
    Then the response status is 200
    And "pick_types" is ["group", "aesthetic", "candid"]
    And the "group" pick is the frame with the highest print_score and source "auto"
    And the "aesthetic" pick is the frame with the highest aesthetic_score and source "auto"
    And the "candid" pick is the frame with the highest candid_score and source "auto"

  @api
  Scenario Outline: Tagging the hero with a criterion records a manual pick
    Given the hero frame is image <iid> in burst 7
    When I press "<key>"
    Then the client POSTs "/api/p/wedding/series/7/pick" with pick_type "<ptype>" and image_id <iid>
    And a toast confirms "<label> → this frame"
    And the pick for "<ptype>" becomes source "manual"

    Examples:
      | key | ptype     | label    | iid |
      | g   | group     | Everyone | 42  |
      | c   | candid    | Candid   | 51  |
      | a   | aesthetic | Striking | 63  |

  @api @persistence
  Scenario: A manual pick overrides the auto pick for that criterion
    Given the auto "candid" pick is image 51
    When I set the "candid" pick to image 88
    And the client requests GET "/api/p/wedding/series/7/picks"
    Then the "candid" pick is image 88 with source "manual"

  @api @persistence
  Scenario: A manual pick survives a regroup and rescore
    Given I have manually set the "group" pick of burst 7 to image 88
    When the pipeline reruns, regrouping series and recomputing scores
    And burst 7 is reloaded in Review
    Then the "group" pick is still image 88 with source "manual"
    And the manual pick was anchored to the image, not to the old series id

  @api
  Scenario: Re-picking the same frame for a criterion toggles the manual pick off
    Given image 88 is the manual "group" pick of burst 7
    When the client POSTs "/api/p/wedding/series/7/pick" with pick_type "group" and image_id 88
    Then the response is ok
    And the manual "group" pick is removed
    And a later GET of the picks shows the "group" pick reverting to the auto choice

  @api @security
  Scenario: Setting a pick to a frame outside the burst is rejected
    When the client POSTs "/api/p/wedding/series/7/pick" with pick_type "group" and image_id 99999
    Then the response status is 400
    And the message is "image not in series"

  @api @security
  Scenario Outline: Setting a pick with a bad payload is rejected
    When the client POSTs "/api/p/wedding/series/7/pick" with pick_type "<ptype>" and image_id <iid>
    Then the response status is 400
    And the message is "bad pick_type / image_id"

    Examples:
      | ptype   | iid  |
      | print   | 42   |
      | bogus   | 42   |
      | group   | null |

  # ---------------------------------------------------------------------------
  # Star → Print list
  # ---------------------------------------------------------------------------

  @ui @api
  Scenario: Starring the hero adds it to the Print list
    Given the hero frame is image 42 and not in the print list
    When I press "Space"
    Then the client POSTs "/api/p/wedding/star/42"
    And the response "starred" is true
    And the star button reads "★ In print list"
    And the stage shows a "★ In print list" badge
    And a toast says "Added to print list"

  @ui @api
  Scenario: Pressing Space again removes the frame from the Print list
    Given image 42 is in the print list
    When I press "Space"
    Then the client POSTs "/api/p/wedding/star/42"
    And the response "starred" is false
    And the star button reads "☆ Add to print list"
    And a toast says "Removed from print list"

  @ui @api
  Scenario: Star the recommended group frame from its own button
    Given the burst's "group" pick is image 42 and it is not in the print list
    When I click "★ Star recommended"
    Then the client POSTs "/api/p/wedding/star/42"
    And a toast says "Starred recommended frame"

  @ui
  Scenario: Star recommended does nothing useful when there is no group pick
    Given the burst has no "group" pick
    When I click "★ Star recommended"
    Then no star request is made
    And a toast says "No recommended frame for this burst"

  @ui
  Scenario: Star recommended is a no-op when the recommended frame is already starred
    Given the "group" pick image is already in the print list
    When I click "★ Star recommended"
    Then no star request is made
    And a toast says "Recommended frame already in print list"

  # ---------------------------------------------------------------------------
  # Range-star
  # ---------------------------------------------------------------------------

  @ui @api
  Scenario: Shift+click range-stars every frame from the hero to the clicked frame
    Given the hero is the 1st frame in the filmstrip
    And none of the first four frames are in the print list
    When I shift+click the 4th frame in the filmstrip
    Then the client POSTs "/api/p/wedding/star_many" with the four frame ids
    And all four frames become starred
    And a toast says "Starred 4 frames"

  @ui
  Scenario: Range-star that selects only already-starred frames does nothing
    Given every frame in the chosen range is already in the print list
    When I shift+click to range-star them
    Then no star request is made
    And a toast says "Already in print list"

  @ui @api
  Scenario: Range-star falls back to individual stars if star_many fails
    Given the hero is the 1st frame and the next two frames are unstarred
    And the "/api/p/wedding/star_many" endpoint returns an error
    When I shift+click the 3rd frame
    Then the client POSTs "/api/p/wedding/star/<id>" once per unstarred frame
    And the frames still end up starred

  # ---------------------------------------------------------------------------
  # Frozen filmstrip order
  # ---------------------------------------------------------------------------

  @ui
  Scenario: Starring a frame does not reorder the filmstrip or bounce me back
    Given the filmstrip is in capture sequence
    And I have scrolled to and selected the 6th frame as hero
    When I press "Space" to star the 6th frame
    Then the 6th frame stays in its position in the filmstrip
    And it remains the current hero
    And the filmstrip does not scroll back to the start

  @ui
  Scenario: The filmstrip stays in capture sequence — featured frames are highlighted in place
    Given burst 7 has a group pick, a candid pick, and two starred frames
    When the burst loads
    Then the filmstrip lists every frame in capture order
    And the picked/starred frames are tagged in place, never hoisted to the front
    And stepping Up/Down moves through that same sequence — selecting or starring never makes it jump

  # ---------------------------------------------------------------------------
  # Keyboard flow
  # ---------------------------------------------------------------------------

  @ui
  Scenario Outline: Keyboard navigation between bursts
    Given I am on burst 2 of 5
    When I press "<key>"
    Then the view moves to burst "<dest>"
    And the new burst's frames and picks are loaded

    Examples:
      | key        | dest |
      | ArrowLeft  | 1    |
      | ArrowRight | 3    |
      | x          | 3    |
      | X          | 3    |

  @ui
  Scenario: Burst navigation wraps around the ends
    Given I am on the last burst
    When I press "ArrowRight"
    Then the view wraps to the first burst

  @ui
  Scenario Outline: Up and Down move the hero through the capture sequence
    When I press "<key>"
    Then the hero moves to the "<dir>" frame in capture order
    And the filmstrip scrolls the new hero into view

    Examples:
      | key       | dir      |
      | ArrowUp   | previous |
      | ArrowDown | next     |

  @ui
  Scenario Outline: Number keys 1–9 toggle the hero into a bucket
    Given the project has bucket <n> defined
    When I press "<key>"
    Then the hero is toggled in or out of bucket <n>
    And the client POSTs "/api/p/wedding/buckets/<bucketId>/toggle" with the hero image_id

    Examples:
      | key | n |
      | 1   | 1 |
      | 2   | 2 |
      | 9   | 9 |

  @ui
  Scenario: Number keys show a hint when no buckets exist
    Given the project has no buckets
    Then the bucket strip reads "No buckets yet — create them in the Buckets tab, then press 1–9 here."

  @ui
  Scenario: Zoom happens in place on the stage and works in fullscreen
    Given the hero frame is image 42
    When I press "Z" (or Enter, or scroll the wheel over the stage)
    Then the hero scales up in place on the stage — there is no separate popup to chase
    And dragging pans the zoomed image and a zoom-percent badge is shown
    And double-clicking resets it to fit
    When I press "F"
    Then the Review view toggles fullscreen
    And zoom still works, because the stage is inside the fullscreened element

  @ui
  Scenario: Keyboard shortcuts are ignored while a lightbox or modal is open
    Given the lightbox is open
    When I press "ArrowRight"
    Then the burst does not change
    And the keypress is handled by the lightbox, not the Review view

  @ui
  Scenario: A help bar documents the keyboard flow
    Then the help fab shows "←→ bursts", "X skip", "↑↓ frames", "Space print", "1–9 buckets", "G/C/A tag", "Z zoom", "I panel", and "F full"

  # ---------------------------------------------------------------------------
  # Inspector — per-person stats (decide who's looking good)
  # ---------------------------------------------------------------------------

  @api
  Scenario: The frame's faces come back with per-person quality stats
    When the client requests GET "/api/p/wedding/image/42/faces"
    Then the response status is 200
    And every face carries "eye_open", "smile", "frontality", "face_sharpness" and "quality_score"
    And each face carries its "person_id" and "display_name" (or null when ungrouped)
    And the faces are ordered largest bounding-box first

  @ui
  Scenario: The inspector lists everyone in the hero frame with their stats
    Given the hero frame has two detected people
    Then the inspector "People in this frame" section shows a row per person
    And each row shows the person's name, face crop, and eyes/smile/frontality mini-bars
    And a low score (eyes below 45%) is shown in a warning colour
    When I press "I"
    Then the inspector panel hides, and pressing "I" again shows it

  # ---------------------------------------------------------------------------
  # Pick feedback — rate the auto picks for retraining
  # ---------------------------------------------------------------------------

  @api @persistence
  Scenario: Rating an auto pick records feedback anchored to the image
    Given the auto "candid" pick of burst 7 is image 51
    When I click 👎 on the "candid" feedback row
    Then the client POSTs "/api/p/wedding/feedback" with pick_type "candid", auto_image_id 51 and verdict "bad"
    And clicking "+ this" while frame 88 is the hero records better_image_id 88
    And the feedback survives a pipeline rerun because it is keyed on the image, not the series id

  @api
  Scenario: Feedback is exportable as a retraining set
    When the client requests GET "/api/p/wedding/feedback/export"
    Then the response lists every verdict joined with the auto frame's path and scores
    And, when a better frame was chosen, that frame's path and scores too

  # ---------------------------------------------------------------------------
  # Resume + reviewed state + resizable / movable panels
  # ---------------------------------------------------------------------------

  @ui @persistence
  Scenario: Burst position and reviewed progress survive a reload
    Given I have stepped through to burst 40 of 907
    When I reload the page
    Then Review resumes at burst 40, not burst 1
    And the top progress bar reflects the bursts already marked reviewed (from the server)

  @api @persistence
  Scenario: Stepping past a burst marks it reviewed on the server
    Given I am on burst 7 and it is not yet reviewed
    When I advance to the next burst
    Then the client POSTs "/api/p/wedding/series/7/reviewed" with reviewed true
    And a later GET of the series shows burst 7 with a non-null "reviewed_at"

  @ui @persistence
  Scenario: The stage / inspector / filmstrip panels resize and move, and the layout persists
    When I drag the vertical divider, the inspector widens and the new width is saved
    And when I drag the horizontal divider, the filmstrip resizes and its height is saved
    And when I click "⇄ move", the inspector swaps to the other side
    And all of these survive a reload via localStorage

  # ---------------------------------------------------------------------------
  # Stale-slug guard + security
  # ---------------------------------------------------------------------------

  @ui @security
  Scenario: Navigating to another project mid-fetch never renders stale frames
    Given burst frames for project "wedding" are still being fetched
    When I switch to project "portraits" before the fetch resolves
    Then the in-flight "wedding" response is discarded on arrival
    And the stage never renders the stale "wedding" frames

  @ui
  Scenario: Stepping to another burst mid-fetch never renders the previous burst
    Given the frames for the current burst are still loading
    When I press "ArrowRight" to advance before they resolve
    Then the stale burst's frames are not rendered when they arrive
    And only the newly selected burst is shown

  @api @security
  Scenario: Series endpoints reject an unknown project
    When the client requests GET "/api/p/does-not-exist/series"
    Then the response status is 404
    And the body describes "no project 'does-not-exist'"
