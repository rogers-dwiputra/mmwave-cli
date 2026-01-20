import time
import mmwcas

config_dict = {
    "mimo": {
        "profile": {
            "id": 0,
            "startFrequency": 77,           # Chirp start frequency in GHz
            "frequencySlope": 79.0327,           # Frequency slope in MHz/us
            "idleTime": 5,                  # Chrip Idle time in us
            "adcStartTime": 6,              # ADC start time in us
            "numAdcSamples": 256,           # Number of ADC samples per chirp
            "adcSamplingFrequency": 8000,  # ADC sampling frequency in ksps
            "rampEndTime": 40,              # Chirp ramp end time in us
            "rxGain": 48,                   # dB
            "txStartTime": 0,               # TX starttime in us
            "hpfCornerFreq1": 0,            # 0: 175kHz
            "hpfCornerFreq2": 0,            # 0: 350kHz
        },
        "frame": {
            "numLoops": 16,                 # Number of chirp loop per frame
            "numFrames": 0,                 # Number of frames to record
            "framePeriodicity": 100,         # Frame periodicity in ms (Inter_Frame_Interval)
        },
        "channel": {
            "rxChannelEn": 0x0F,            # Enable all 4 RX channels
            "txChannelEn": 0x07,            # Enable all 3 TX channels
        }
    }
}

record_duration = 10
status = mmwcas.mmw_set_config(config_dict)
if status!=0:
    print(status)
    raise ValueError(f"{status}")

status = mmwcas.mmw_init()
assert status==0,ValueError
time.sleep(2)
status = mmwcas.mmw_arming_tda("mmwave_python_20250120_1637")
assert status==0,ValueError
time.sleep(2)
status = mmwcas.mmw_start_frame()
assert status==0,ValueError

time.sleep(record_duration)

status=mmwcas.mmw_stop_frame()
assert status==0,ValueError
status=mmwcas.mmw_dearming_tda()
assert status==0,ValueError