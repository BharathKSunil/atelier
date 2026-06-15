Feature: People — clustering, browse, and manual identity edits
  As someone culling a photo library
  I want faces automatically grouped into people and easy ways to correct the grouping
  So that I can find, name, and export everyone's photos without the machine's mistakes sticking around

  Background:
    Given a project exists with slug "wedding"
    And the face index has been built for that project
    And every state-changing request carries a valid "X-Atelier-Token" header
    And requests are made from a local host

  # ----------------------------------------------------------------------------
  # Clustering (pipeline/cluster.py)
  # ----------------------------------------------------------------------------

  @clustering
  Scenario: Faces are clustered into people via HDBSCAN on normalized embeddings
    Given the project has faces with 512-d embeddings
    When the clustering pass runs over the L2-normalized embeddings
    Then HDBSCAN assigns each face a cluster label
    And every face sharing a cluster label is written to the same "person_id"
    And one "persons" row is created per non-noise cluster
    And the run prints a summary of persons, faces, and noise counts

  @clustering
  Scenario: Centroid-cosine merge collapses fragments of the same person
    Given two clusters whose L2-normalized centroids have cosine similarity at or above the merge threshold
    When the clustering pass runs with a positive "--merge-cosine"
    Then the two clusters are unioned into a single person
    And faces that were split across pose or lighting end up under one identity

  @clustering
  Scenario: Centroid merge is disabled when the threshold is zero
    Given two distinct clusters
    When the clustering pass runs with "--merge-cosine 0"
    Then no centroid-based merge is performed
    And the clusters remain separate people

  @clustering @edge
  Scenario: Noise faces become ungrouped rather than grouped
    Given some faces that HDBSCAN cannot place in any cluster
    When the clustering pass runs
    Then those faces are written with "person_id" of -1
    And no "persons" row is created for the noise
    And the ungrouped faces remain browsable but identity-less

  @clustering @edge
  Scenario: Clustering on an empty face set does nothing
    Given the project has no faces with embeddings
    When the clustering pass runs
    Then it reports "no faces — run 01_index.py first"
    And no persons are created

  @clustering @persistence
  Scenario: A custom name is inherited across a re-cluster by face overlap
    Given a person named "Aunt Mei" whose faces are mostly re-grouped together by the next run
    When the clustering pass runs again
    Then the freshly-formed cluster with the greatest face overlap is named "Aunt Mei"
    And auto-generated "Person N" names are never carried forward

  # ----------------------------------------------------------------------------
  # Browse — people grid (web/people.js, GET /persons)
  # ----------------------------------------------------------------------------

  @ui @api
  Scenario: The People grid lists people ordered by photo count
    When the user opens the People view
    Then a request is made to "GET /api/p/wedding/persons?offset=0&limit=60"
    And each person shows a best-face thumbnail, a display name, and a photo count
    And people are ordered by descending face count

  @ui @api
  Scenario Outline: Pagination clamps the requested page size
    When the user requests people with "limit=<requested>" and "offset=<requested_offset>"
    Then the server serves at most <effective_limit> people
    And the offset used is <effective_offset>

    Examples:
      | requested | requested_offset | effective_limit | effective_offset |
      | 60        | 0                | 60              | 0                |
      | 9999      | 0                | 500             | 0                |
      | 0         | -5               | 1               | 0                |
      | abc       | xyz              | 60              | 0                |

  @ui @api
  Scenario: Infinite scroll loads the next page when the sentinel appears
    Given the first page of people returns a non-null "next_offset"
    When the user scrolls the grid so the sentinel enters view
    Then the next page is fetched at that "next_offset"
    And the new people are appended below the existing ones

  @ui @api
  Scenario: Reaching the end stops further loading
    Given a page of people returns "next_offset" of null
    When that page renders
    Then the sentinel is removed
    And no further person pages are requested

  @ui @api
  Scenario: Searching filters people by name
    When the user types "mei" into the people search box
    Then after a short debounce a request is made with "q=mei"
    And only people whose display name contains "mei" case-insensitively are returned
    And the grid resets to the first page for the new query

  @ui @api @edge
  Scenario: A search with no matches shows an empty grid
    When the user searches for a name no person has
    Then the server returns zero people with a total of 0
    And the grid renders empty without error

  # ----------------------------------------------------------------------------
  # Person detail (web/people.js, GET /persons/<id>/faces)
  # ----------------------------------------------------------------------------

  @ui @api
  Scenario: Opening a person shows that person's faces, best first
    When the user clicks a person in the grid
    Then a request is made to "GET /api/p/wedding/persons/<id>/faces?offset=0&limit=100"
    And the faces are ordered best-first then by descending quality
    And the header photo count is corrected from the authoritative faces total once the first page lands

  # ----------------------------------------------------------------------------
  # Rename (POST /persons/<id>/rename)
  # ----------------------------------------------------------------------------

  @ui @api
  Scenario: Renaming a person persists the new name
    Given the user is viewing the person detail for person 3
    When the user edits the name to "Grandpa Joe" and clicks "Save"
    Then a request is made to "POST /api/p/wedding/persons/3/rename" with name "Grandpa Joe"
    And the response is "ok": true
    And a "Renamed" toast is shown
    And the view returns to the People grid

  @api @persistence
  Scenario: A rename survives a re-cluster
    Given person 3 was renamed to "Grandpa Joe"
    When the clustering pass runs again
    Then the override group covering those faces still carries "Grandpa Joe"
    And the rebuilt person for those faces shows "Grandpa Joe"

  # ----------------------------------------------------------------------------
  # Merge (POST /persons/merge)
  # ----------------------------------------------------------------------------

  @ui @api
  Scenario: Merging one person into another folds all faces together
    Given the user is viewing person 5 named "Bob"
    When the user opens "Merge into…", picks person 8 named "Robert", and confirms
    Then a request is made to "POST /api/p/wedding/persons/merge" with from_id 5 and into_id 8
    And every face of person 5 is moved onto person 8
    And the now-empty person 5 row is deleted
    And a "Merged into Robert" toast is shown

  @api @validation
  Scenario Outline: Merge rejects missing or identical ids
    When a client posts to "/api/p/wedding/persons/merge" with from_id "<from>" and into_id "<into>"
    Then the response status is 400
    And the body says "need distinct from_id / into_id"

    Examples:
      | from | into |
      | null | 8    |
      | 5    | null |
      | 7    | 7    |

  @api @persistence
  Scenario: A merge survives a re-cluster
    Given person 5 was merged into person 8
    When the clustering pass runs again
    Then all faces from both original people are re-imposed onto a single identity
    And they do not split back into two people

  @api @persistence @edge
  Scenario: The merge-orphan face stays merged across a second merge
    Given person A was previously merged into person B under one override group
    And one face from that group later drifted to noise so it now sits at "person_id" -1
    When person C is merged into B
    Then the drifted face's stale override group is re-keyed onto B's group
    And on the next re-cluster that orphan face stays with B rather than re-materializing a separate person

  # ----------------------------------------------------------------------------
  # Split (POST /persons/<id>/split)
  # ----------------------------------------------------------------------------

  @ui @api
  Scenario: Splitting selected faces creates a new person
    Given the user is viewing a person and has ticked 4 of their faces
    When the user clicks "Split out (4)" and names the new person "Cousin Lee"
    Then a request is made to "POST /api/p/wedding/persons/<id>/split" with those 4 face ids and name "Cousin Lee"
    And a brand-new person is created from those faces with the next free id
    And a "Split into a new person" toast is shown

  @ui
  Scenario: An unnamed split falls back to a derived name
    Given the user is splitting faces out of person "Bob"
    When the user leaves the name blank and confirms
    Then the new person is named "Bob (split)"

  @ui @edge
  Scenario: Cancelling the split prompt makes no change
    Given the user clicked "Split out" with faces selected
    When the user dismisses the name prompt
    Then no split request is sent

  @api @validation
  Scenario: Split with no faces is rejected
    When a client posts to "/api/p/wedding/persons/3/split" with an empty face list
    Then the response status is 400
    And the body says "no faces selected"

  @api @persistence
  Scenario: A split survives a re-cluster
    Given faces were split out into "Cousin Lee"
    When the clustering pass runs again
    Then the split group is re-imposed as its own person
    And those faces are never folded back into their original cluster

  # ----------------------------------------------------------------------------
  # Not this person — reassign / reject / similar (web/faces.js)
  # ----------------------------------------------------------------------------

  @ui @api
  Scenario: "Not this person" → extract makes a new person from the one face
    Given the user opened the face detail modal for a grouped face on person 6
    When the user clicks "Not this person" then "Make a new person from this face"
    Then a request is made to "POST /api/p/wedding/persons/6/split" with that single face id
    And an "Extracted into a new person" toast is shown
    And the modal closes and an "atelier:people-changed" event fires

  @ui @api
  Scenario: "Not this person" → remove, with no similar faces, just removes the face
    Given the user opened the face detail modal for a grouped face on person 6
    When the user clicks "Not this person" then "Remove from this person"
    Then a request is made to "POST /api/p/wedding/faces/reject" with that face id
    And the face is forced to ungrouped ("person_id" -1) and cleared as best
    And similar faces are looked up via "GET /api/p/wedding/faces/<fid>/similar?person=6&threshold=0.5"
    And when no similar faces come back a "Removed from person" toast is shown and the modal closes

  @ui @api
  Scenario: Removing a face offers a visual review of similar faces to also remove
    Given the user chose "Remove from this person" for a face on person 6
    And the similar lookup returns several in-person faces above the threshold
    When the review grid renders
    Then each similar face shows its percent likeness
    And faces at or above 0.6 cosine are pre-checked
    And the user can "Remove selected" or "Keep them"

  @ui @api
  Scenario: Confirming the similar review rejects all the ticked faces plus the original
    Given the similar-faces review grid is showing 3 pre-checked faces
    When the user clicks "Remove selected"
    Then a request is made to "POST /api/p/wedding/faces/reject" with the 3 ticked face ids
    And a "Removed 4 faces" toast is shown counting the original plus the 3
    And the modal closes and an "atelier:people-changed" event fires

  @ui
  Scenario: "Keep them" in the similar review removes only the original face
    Given the similar-faces review grid is showing
    When the user clicks "Keep them"
    Then no further reject request is sent
    And a "Removed 1 face" toast is shown for the originally-removed face

  @ui @edge
  Scenario: Ungrouped faces offer no "Not this person" action
    When the user opens the face detail modal for a face whose "person_id" is -1
    Then the face is labelled "Ungrouped"
    And no "Not this person" button is shown

  @api @persistence
  Scenario: A rejected face stays ungrouped across a re-cluster
    Given a face was rejected as "not a person"
    When the clustering pass runs again
    Then the reject override forces that face back to "person_id" -1
    And it is never allocated to a person

  @api @validation
  Scenario: Reassigning a face requires a target person
    When a client posts to "/api/p/wedding/faces/12/reassign" with no person_id
    Then the response status is 400
    And the body says "need person_id"

  @api
  Scenario: Reassigning a face joins it to the target person's identity group
    When a client posts to "/api/p/wedding/faces/12/reassign" with person_id 8
    Then face 12 is moved onto person 8
    And it joins person 8's override group so the move survives a re-cluster

  @api @validation
  Scenario: The similar-faces endpoint rejects unparseable params
    When a client requests "/api/p/wedding/faces/12/similar?person=foo&threshold=bar"
    Then the response status is 400
    And the body says "bad params"

  # ----------------------------------------------------------------------------
  # People-changed refresh (web/people.js listener)
  # ----------------------------------------------------------------------------

  @ui
  Scenario: An open person refreshes in place after a face edit
    Given the user is viewing a person's detail on the People view
    When an "atelier:people-changed" event fires after a reject or extract
    Then that person's faces are re-fetched
    And the header photo count is corrected from the new total

  @ui @edge
  Scenario: The people-changed refresh is skipped when not on the People view
    Given no person detail is open or the People view is hidden
    When an "atelier:people-changed" event fires
    Then no re-fetch happens

  # ----------------------------------------------------------------------------
  # Security & project guards (server.py before_request, _require)
  # ----------------------------------------------------------------------------

  @security @api
  Scenario: A state-changing person request without the token is rejected
    When a client posts to "/api/p/wedding/persons/3/rename" without the "X-Atelier-Token" header
    Then the response status is 403
    And the description is "missing or invalid request token"

  @security @api
  Scenario: A cross-origin person request is blocked
    When a client posts to "/api/p/wedding/persons/merge" with a non-local "Origin" header
    Then the response status is 403
    And the description is "cross-origin request blocked"

  @security @api
  Scenario: A request to a non-local host is refused
    When a client calls any "/api/p/wedding/persons" route with a non-local host
    Then the response status is 403
    And the description is "non-local host"

  @api @edge
  Scenario: Operating on an unknown project returns 404
    When a client requests people for slug "does-not-exist"
    Then the response status is 404
    And the description is "no project 'does-not-exist'"
