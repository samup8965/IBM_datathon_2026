# Evidence: Venezuela outage forecaster on IBM LinuxONE

Collected 2026-10-17 21:11 UTC from `evidence/2026-10-17_2110`

## Machine
```
date (UTC): Sat Oct 17 21:10:42 UTC 2026
Linux sams-instance 6.8.0-147-generic #147-Ubuntu SMP Thu Sep 24 10:59:43 UTC 2026 s390x GNU/Linux
processor 0: version = FF,  identification = 07DFD8,  machine = 9175
Manufacturer:         IBM             
Type:                 9175
Model:                702              ME1             
LPAR Name:            IBM20   
LPAR CPUs Total:      40
VM00 Name:            L5014F8F
VM00 Control Program: z/VM    7.3.0   
```

## Code version
```
commit c3c0c9a84baa7e9cdc6b733c5ae90b70ffd21d94
author Samuel Parra Centeno, Sat Oct 17 22:07:04 2026 +0100
Add LinuxONE evidence collector; fix data-age to use Venezuela time
```

## Telum NNPA: the trained forecaster
```
Trained forecaster: 5 neural networks scoring 50,000 state-hours
  on nnpa:0:     78.6 ms
  on cpu :    102.4 ms   (1.3x)
  largest difference between the two: 1.34e-03 (non-zero: the NNPA did the work)
```

## Telum NNPA: benchmark
```
Machine: {'python': '3.12.15', 'arch': 's390x', 'cpu': 'processor 0: version = FF,  identification = 07DFD8,  machine = 9175'}
== pytorch 2.11.0+cpu | NNPA device: nnpa
   mlp  on cpu :     1.49 ms per batch of 4096
   mlp  on nnpa:     0.14 ms per batch of 4096
   mlp  NNPA used? YES - answers differ slightly, as expected from NNPA's 16-bit math (max diff 1.18e-03, 10.64x vs CPU)
   lstm on cpu :   739.04 ms per batch of 4096
   lstm on nnpa:   768.16 ms per batch of 4096
   lstm NNPA used? YES - answers differ slightly, as expected from NNPA's 16-bit math (max diff 3.93e-04, 0.96x vs CPU)
== tensorflow 2.18.1 | NNPA device: None
   mlp  on cpu :     2.07 ms per batch of 4096
   lstm on cpu :   233.09 ms per batch of 4096
```

## Results on real 2025-26 outages (trained on real 2022-24, on this machine)
```
Model comparison (test set)
base rate (the floor)            PR-AUC 0.326
recent outages (roll24)          PR-AUC 0.665 | ROC-AUC 0.780
regional average                 PR-AUC 0.407 | ROC-AUC 0.602
same as yesterday                PR-AUC 0.561 | ROC-AUC 0.756
gradient boosting alone          PR-AUC 0.755 | ROC-AUC 0.853
PyTorch ensemble alone           PR-AUC 0.767 | ROC-AUC 0.857
blend (NN share 0.50), raw       PR-AUC 0.765 | ROC-AUC 0.858

Risk levels (calibrated probability of an outage within 24 rows): Moderate >= 0.076 | Severe >= 0.120 | Critical >= 0.387

Final model, calibrated (test set)
final model (flagging Severe+)   PR-AUC 0.753 | ROC-AUC 0.857 | prec 0.549 | rec 0.866 | F1 0.672
log loss 0.4707 | Brier 0.1534

Do the risk levels mean something? (test set; the outage rate should rise with the level)
  Low       rows   72370 | actual outage rate 0.058 | share of all outages 0.05
  Moderate  rows   59766 | actual outage rate 0.129 | share of all outages 0.09
  Severe    rows   68678 | actual outage rate 0.330 | share of all outages 0.26
  Critical  rows   71681 | actual outage rate 0.759 | share of all outages 0.61

```

## Prediction run
```
  neural networks score on: nnpa
Data is current up to 2026-10-17 13:00:00 (0 days 04:10:35 ago); risk = chance of an outage starting in the next 24 rows.
```
