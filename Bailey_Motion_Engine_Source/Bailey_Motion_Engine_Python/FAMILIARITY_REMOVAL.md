# Familiarity removed from behavioral utility

Both runtime behavior modes now use:

```text
behavioral utility = -wT*T + wP*P - wN*N - wS*C
```

There is no H feature, sampled wH, habit reward, or familiarity utility setting.
The change removes the factor rather than assigning it a zero coefficient.
The optional distance, panic, residual, and legacy crowd terms are otherwise
unchanged, as are physical motion, door rules, and the decision interval.

Functional changes:

1. Removed familiarity from the local dot product and legacy utility calculation.
2. Removed H from current decision feature records and diagnostics.
3. Changed the joint lognormal sampler from five weights to four: T, P, N, S.
   It retains the centering `mu = -sigma^2/2`, expected vector `(1,1,1,1)`,
   positive unbounded weights, and no fixed-sum normalization.
4. Updated the equicorrelation constraint to `-1/3 < weightRho < 1`.
5. Removed unused habit values and familiarity flags from runtime routing.
6. Removed `familiarBuildingExit` from bundled settings. The runtime ignores
   that removed key when older settings are loaded.
7. Removed wH from expanded CSV headers/rows. JSON weights contain four entries.
8. Renamed admission memory's `familiarTargets` to `knownTargets`. Arrival paths
   retain their separate function of remembering where targets are; they do
   not change any utility feature or give a remembered route a preference bonus.
9. Updated existing behavioral examples and tests for the four-factor equation.
   Former habit-only example A13 now has the same behavioral preference as the
   time-only profile; B07's example utilities become -2.0 and -1.6.
10. Preserved original JavaScript trajectory comparisons using a frozen
    five-weight policy under `tests/archived_five_weight_policy.py`. It is a
    test fixture, never selected by runtime mode switches, CLI, or GUI.
11. Added focused removal checks in `tests/test_no_familiarity.py`. Every engine
    instantiated by that verification has exactly 300 participants.
12. Updated README guidance and marked earlier change logs as historical.

Current weightSigma, weightRho, timeScale, and the three-second decision interval
are retained. Changing the sampler dimension changes the seeded random-draw
sequence, so new weights, panic draws, and trajectories will differ from prior
five-weight runs even with the same seed. Earlier saved outputs remain historical.

Restart the GUI or restore/apply the bundled source to load the updated model:

```powershell
python run.py --gui
```

The model still optimizes utility rather than always choosing the nearest door:
peer influence, norm penalties, switching costs, perceived waiting, and the
remaining utility terms can still favor a longer path. Remembered targets can
remain available outside current sight; that is wayfinding knowledge, not an
added familiarity reward.

Verification: all seven focused checks passed, with 300 participants in every
engine. The seed-2026 run cleared all 300 units in approximately 60.4 simulated
seconds. Saved utilities, maximizing choices, four-column weight exports, and
first-floor crossing records were checked. Outputs are
`results/no-familiarity-300-seed2026.json` / `.csv`; the report is
`results/no-familiarity-verification.json`. The mixed-population full test suite
was not rerun because further simulation runs were restricted to n = 300.
