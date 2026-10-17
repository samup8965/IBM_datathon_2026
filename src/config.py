"""
src/config.py - THE ONLY FILE YOU NEED TO EDIT.

Tell the program where each dataset is and what its columns are called.
Every file must have a time column; regional files also need a region column.
"""

CONFIG = {
    # Predict outages in the next N rows. 24 = "next 24 hours" if your data is hourly.
    "horizon": 24,

    # True: learn only from moments when power is currently ON, i.e. predict outage *onset*.
    # (Otherwise the model mostly learns "outages continue".)
    "exclude_ongoing": True,

    # How old a reading may be before it counts as missing (e.g. "3D" = 3 days).
    "default_tolerance": "3D",

    # If your history has gaps in time, set this to e.g. "h" to rebuild a complete hourly grid
    # (missing hours are assumed to have NO outage). None = use the rows exactly as given.
    "regularize_freq": None,

    # HISTORY = the base table: it decides which (time, region) rows the model sees.
    # Two formats:
    #   "grid"  : one row per (timestamp, region) with a 0/1 outage column
    #   "events": one row per outage with start/end times (also give "start", "end", "freq")
    # The LAST timestamp in this file is treated as "now" when predicting.
    "history": {
        "path": "history.csv", "format": "grid",
        "time": "timestamp", "region": "region", "target": "outage",
    },

    # The other datasets. region=None means country-level (copied to every region).
    #   cols=[...]            numeric columns to use
    #   roll=[(stat, window)] rolling mean/max/min/std over the past `window` rows
    #   diff=[k]              change versus k rows ago
    #   rel_to_median=W       value divided by its own median over the previous W rows
    #                         (a drop shows up as a number below 1 - good for connectivity)
    #   tolerance="10D"       optional: how stale this dataset's readings may be
    # Only inputs that exist for BOTH the synthetic training data and the real test data
    # (scripts/export_model_input.py). Temperature (not simulated) and reservoir (no real
    # data) are left out; add them back here if both datasets get them.
    "sources": [
        {"name": "heat", "path": "heat_index.csv", "time": "timestamp", "region": "region",
         "cols": ["heat_index"], "roll": [("max", 24), ("mean", 72)], "diff": [24]},
        {"name": "net", "path": "connectivity.csv", "time": "timestamp", "region": "region",
         "cols": ["connectivity"], "roll": [("min", 24)], "rel_to_median": 168},
    ],

    "lags": [1, 6, 24],      # past outage values, in rows
    "windows": [24, 168],    # rolling outage counts, in rows
}

# ----------------------------------------------------------------- training settings
TRAIN_FRAC, VAL_FRAC = 0.70, 0.15  # time-ordered split; the last 15% (newest data) is the test set
N_SEEDS = 5                        # number of neural networks averaged together
EMB_DIM = 8                        # size of the learned vector describing each region
MAX_EPOCHS, PATIENCE, BATCH = 100, 10, 256
USE_POS_WEIGHT = True              # make the network take rare outages seriously (False if common)
POS_WEIGHT_CAP = 50.0
BLEND_WEIGHTS = [0.25, 0.5, 0.75, 1.0]   # share given to the neural net in the final blend (always > 0)

# ----------------------------------------------------------------- risk levels
# Risk levels say how the current situation compares with HISTORY. Using the validation period as
# the yardstick, "Critical" = riskier than ~90% of past situations, "Severe" = riskier than ~70%,
# "Moderate" = riskier than ~40%, "Low" = the rest. The share of rows in each level is therefore
# (roughly) fixed in history; in a calmer period more regions will show Low.
TIER_SHARES = {"Moderate": 0.60, "Severe": 0.30, "Critical": 0.10}   # share of history at or above each level

# ----------------------------------------------------------------- data confidence
MIN_POSITIVES = 30         # warn if a split has fewer outage examples than this
CONF_HIGH, CONF_MED = 30, 10   # outage EVENTS seen in a region's history -> High / Medium confidence
