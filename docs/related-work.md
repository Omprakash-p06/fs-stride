# Related Work & Citation Notes

## False-Sharing Detection Tools vs. Stride-Knee Measurement

Counter-based and instrumentation-based tools detect *where* false sharing occurs in an existing program, rather than measuring *how far apart* per-thread data must be padded on a given CPU:

- **SC'13 Classifier:** Jayasena et al., *Detection of False Sharing Using Machine Learning*, SC'13.
- **SHERIFF:** Liu and Berger, OOPSLA 2011.
- **PREDATOR:** Liu et al., PPoPP 2014.
- **Cheetah:** Liu and Liu, CGO 2016.
- **Huron:** Khan et al., PLDI 2019 (`efeslab/huron`).
- **FSDetect / FSLite:** Patel, Biswas, and Chaudhuri, *MICRO 2024*, pp. 823–839 (DOI `10.1109/MICRO61859.2024.00066`).
- **Multi-socket coherence latency:** David, Guerraoui, and Trigonakis, *SOSP 2013*, pp. 33–48.
- **Linux `perf c2c` (`--double-cl`):** Feng Tang, February 2023 patch (`lore.kernel.org/r/20230214075823.246414-1-feng.tang@intel.com`).

## Benchmarking & Statistical Methodology

- Georges, Buytaert, and Eeckhout, *Statistically Rigorous Java Performance Evaluation*, OOPSLA 2007, pp. 57–76 (DOI `10.1145/1297027.1297033`).
- Mytkowicz, Diwan, Hauswirth, and Sweeney, *Producing Wrong Data Without Doing Anything Obviously Wrong!*, ASPLOS 2009, pp. 265–276 (DOI `10.1145/1508284.1508275`).
- Kalibera and Jones, *Rigorous Benchmarking in Reasonable Time*, ISMM 2013, pp. 63–74 (DOI `10.1145/2464157.2464160`).

## Production Motivating Bugs (CPython)

Both CPython issues are cited for distinct root causes:

- **CPython `gh-144438` (February 2026, PR #144554):** Fixed false sharing between the QSBR array and an adjacent thread-state field by aligning to 64 B.
- **CPython Issue `#159860` (October 2026, free-threaded 3.13–3.15):** Showed that 64 B QSBR thread-state padding limited 14-core CPU-bound thread scaling on Apple M4 Pro (~6× vs ~10× for separate processes) due to 128 B L2/SLC granularity, requiring a move from 64 B to 128 B padding.
