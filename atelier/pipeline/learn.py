#!/usr/bin/env python3
"""Phase 5 (optional) — train the learned pick-ranking head from feedback + bucket
keeps, offline. Writes images.learned_score and persists the model in learned_models.
Below config.LEARN_MIN_PAIRS preference pairs it keeps the heuristic untouched."""

import argparse

from atelier import config, db, learning


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="faces.db")
    ap.add_argument("--pick-type", default="print", choices=list(learning.PICK_ANCHOR))
    args = ap.parse_args()

    conn = db.connect(args.db)
    res = learning.fit(conn, args.pick_type)
    if not res["trained"]:
        print(
            f"only {res['n_pairs']} preference pairs (< {config.LEARN_MIN_PAIRS}); "
            "keeping the heuristic, no model trained"
        )
        return
    print(
        f"trained '{args.pick_type}' on {res['n_pairs']} pairs; "
        f"train ranking accuracy {res['train_acc']:.2f}; wrote images.learned_score"
    )


if __name__ == "__main__":
    main()
