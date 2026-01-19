#from libc.stdio cimport printf as DEBUG_PRINT
from libc.stdio cimport printf
from libc.stdint cimport uint8_t, int8_t,int16_t,uint16_t, int32_t, uint32_t
from libc.math cimport ceil

cdef extern from "ti/mmwave/mmwave.h":
    '''
    FILE* rls_traceF = NULL;
    void CloseTraceFile() {
    if (rls_traceF != NULL) {
        fclose(rls_traceF);
        rls_traceF = NULL;
    }
    }
    '''
    ctypedef struct rlProfileCfg_t:
        uint16_t profileId
        uint8_t pfVcoSelect
        uint8_t pfCalLutUpdate
        uint32_t startFreqConst
        uint32_t idleTimeConst
        uint32_t adcStartTimeConst
        uint32_t rampEndTime
        uint32_t txOutPowerBackoffCode
        uint32_t txPhaseShifter
        int16_t freqSlopeConst
        int16_t txStartTime
        uint16_t numAdcSamples
        uint16_t digOutSampleRate
        uint8_t hpfCornerFreq1
        uint8_t hpfCornerFreq2
        uint16_t txCalibEnCfg
        uint16_t rxGain
        uint16_t reserved

    ctypedef struct rlFrameCfg_t:
        uint16_t reserved0
        uint16_t chirpStartIdx
        uint16_t chirpEndIdx
        uint16_t numLoops
        uint16_t numFrames
        uint16_t numAdcSamples
        uint32_t framePeriodicity
        uint16_t triggerSelect
        uint16_t reserved1
        uint32_t frameTriggerDelay

    ctypedef struct rlChirpCfg_t:
        uint16_t chirpStartIdx
        uint16_t chirpEndIdx
        uint16_t profileId
        uint16_t reserved
        uint32_t startFreqVar
        uint16_t freqSlopeVar
        uint16_t idleTimeVar
        uint16_t adcStartTimeVar
        uint16_t txEnable
    
    ctypedef struct rlChanCfg_t:
        uint16_t rxChannelEn
        uint16_t txChannelEn
        uint16_t cascading
        uint16_t cascadingPinoutCfg
    
    ctypedef struct rlAdcBitFormat_t:
        uint32_t b2AdcBits
        uint32_t b6Reserved0
        uint32_t b8FullScaleReducFctr
        uint32_t b2AdcOutFmt
        uint32_t b14Reserved1

    ctypedef struct rlAdcOutCfg_t:
        rlAdcBitFormat_t fmt
        uint16_t reserved0
        uint16_t reserved1

    ctypedef struct rlDevDataFmtCfg_t:
        uint16_t rxChannelEn
        uint16_t adcBits
        uint16_t adcFmt
        uint8_t iqSwapSel
        uint8_t chInterleave
        uint32_t reserved
    
    ctypedef struct rlRfLdoBypassCfg_t:
        uint16_t ldoBypassEnable
        uint8_t supplyMonIrDrop
        uint8_t ioSupplyIndicator
    
    ctypedef struct rlLowPowerModeCfg_t:
        uint16_t reserved
        uint16_t lpAdcMode
    
    ctypedef struct rlRfMiscConf_t:
        uint32_t miscCtl
        uint32_t reserved
    
    ctypedef struct rlDevDataPathCfg_t:
        uint8_t intfSel
        uint8_t transferFmtPkt0
        uint8_t transferFmtPkt1
        uint8_t cqConfig
        uint8_t cq0TransSize
        uint8_t cq1TransSize
        uint8_t reserved

    ctypedef struct rlDevDataPathClkCfg_t:
        uint8_t laneClkCfg
        uint8_t dataRate
        uint16_t reserved

    ctypedef struct rlDevHsiClk_t:
        uint16_t hsiClk
        uint16_t reserved

    ctypedef struct rlDevCsi2Cfg_t:
        uint32_t lanePosPolSel
        uint8_t lineStartEndDis
        uint8_t reserved0
        uint16_t reserved0
    
    ctypedef struct rlTdaArmCfg_t:
        unsigned int framePeriodicity
        unsigned char* captureDirectory
        unsigned int numberOfFilesToAllocate
        unsigned int dataPacking
        unsigned int numberOfFramesToCapture

    int MMWL_chirpConfig(unsigned char deviceMap, rlChirpCfg_t chirpCfgArgs)
    unsigned int createDevMapFromDevId(unsigned char devId)
    int MMWL_DevicePowerUp(unsigned char deviceMap, uint32_t rlClientCbsTimeout, uint32_t sopTimeout)
    int MMWL_firmwareDownload(unsigned char deviceMap)
    int MMWL_setDeviceCrcType(unsigned char deviceMap)
    int MMWL_rfEnable(unsigned char deviceMap)
    int MMWL_channelConfig(unsigned char deviceMap, unsigned short cascade, rlChanCfg_t rfChanCfgArgs)
    int MMWL_adcOutConfig(unsigned char deviceMap, rlAdcOutCfg_t adcOutCfgArgs)
    int MMWL_RFDeviceConfig(unsigned char deviceMap)
    int MMWL_ldoBypassConfig(unsigned char deviceMap, rlRfLdoBypassCfg_t rfLdoBypassCfgArgs)
    int MMWL_dataFmtConfig(unsigned char deviceMap, rlDevDataFmtCfg_t dataFmtCfgArgs)
    int MMWL_lowPowerConfig(unsigned char deviceMap, rlLowPowerModeCfg_t rfLpModeCfgArgs)
    int MMWL_ApllSynthBwConfig(unsigned char deviceMap)
    int MMWL_setMiscConfig(unsigned char deviceMap, rlRfMiscConf_t miscCfg)
    int MMWL_rfInit(unsigned char deviceMap)
    int MMWL_dataPathConfig(unsigned char deviceMap, rlDevDataPathCfg_t datapathCfgArgs)
    int MMWL_hsiClockConfig(unsigned char deviceMap, rlDevDataPathClkCfg_t datapathClkCfgArgs, rlDevHsiClk_t hisClkgs)
    int MMWL_CSI2LaneConfig(unsigned char deviceMap, rlDevCsi2Cfg_t CSI2LaneCfgArgs)
    int MMWL_profileConfig(unsigned char deviceMap, rlProfileCfg_t profileCfgArgs)
    int MMWL_frameConfig(unsigned char deviceMap, rlFrameCfg_t frameCfgArgs, rlChanCfg_t channelCfgArgs, rlAdcOutCfg_t adcOutCfgArgs, rlDevDataPathCfg_t datapathCfgArgs, rlProfileCfg_t profileCfgArgs)
    int MMWL_AssignDeviceMap(unsigned char deviceMap,uint8_t* masterMap,uint8_t* slavesMap)
    int MMWL_ArmingTDA(rlTdaArmCfg_t tdaArmCfgArgs)
    int MMWL_StartFrame(unsigned char deviceMap)
    int MMWL_StopFrame(unsigned char deviceMap)
    int MMWL_DeArmingTDA()
    int MMWL_TDAInit(unsigned char *ipAddr , unsigned int port,uint8_t deviceMap)




# Define program constants
cdef char* PROG_NAME = b"mmwcas"
cdef char* PROG_VERSION = b"0.2-TDM-MIMO"
cdef char* PROG_COPYRIGHT = b"Copyright (C) 2024"

cdef int RL_RET_CODE_OK = 0

# Development environment flag
cdef int DEV_ENV = 1
cdef int NUM_CHIRPS = 12

cdef char* CRED=b"\e[0;31m"
cdef char* CGREEN=b"\e[0;32m"
cdef char* CRESET=b"\e[0m"

cdef int TRUE = 1


# Device configuration structure
ctypedef struct devConfig_t:
    uint8_t deviceMap
    uint8_t masterMap
    uint8_t slavesMap

    rlFrameCfg_t frameCfg
    rlFrameCfg_t frameCfgSlave  # NEW: Separate frame config for slaves
    rlProfileCfg_t profileCfg
    rlChirpCfg_t chirpCfg
    rlChanCfg_t channelCfg
    rlAdcOutCfg_t adcOutCfg
    rlDevDataFmtCfg_t dataFmtCfg
    rlRfLdoBypassCfg_t ldoCfg
    rlLowPowerModeCfg_t lpmCfg
    rlRfMiscConf_t miscCfg
    rlDevDataPathCfg_t datapathCfg
    rlDevDataPathClkCfg_t datapathClkCfg
    rlDevHsiClk_t hsClkCfg
    rlDevCsi2Cfg_t csi2LaneCfg

"""! \brief
* Profile config API parameters - UPDATED FOR TDM-MIMO
* These are DEFAULT values that will be overridden by Python config
"""
cdef rlProfileCfg_t profileCfgArgs=rlProfileCfg_t(
    profileId = 0,
    pfVcoSelect = 0x02,            # VCO2 for 77-81 GHz
    startFreqConst = 1435384036,   # ~77 GHz (will be overridden)
    freqSlopeConst = 311,          # ~15 MHz/us (will be overridden)
    idleTimeConst = 700,           # 7 us (will be overridden)
    adcStartTimeConst = 434,       # 4.34 us (will be overridden)
    rampEndTime = 6897,            # 68.97 us (will be overridden)
    txOutPowerBackoffCode = 0x0,
    txPhaseShifter = 0x0,
    txStartTime = 0x0,
    numAdcSamples = 512,           # Will be overridden
    digOutSampleRate = 8000,       # 8 MHz
    hpfCornerFreq1 = 0x0,          # 175kHz
    hpfCornerFreq2 = 0x0,          # 350kHz
    rxGain = 48,                   # 48 dB
)

"""! \brief
* Frame config API parameters - UPDATED FOR TDM-MIMO
"""
cdef rlFrameCfg_t frameCfgArgs=rlFrameCfg_t(
    chirpStartIdx = 0,
    chirpEndIdx = 11,              # 12 chirps (0-11) for TDM-MIMO
    numFrames = 20,                # Default 20 frames (will be overridden)
    numLoops = 10,                 # 10 chirp loops per frame
    numAdcSamples = 2 * 512,       # Complex samples
    frameTriggerDelay = 0x0,
    framePeriodicity = 2000000,    # 10ms (will be overridden)
    triggerSelect = 1,             # Default: Software trigger (Master)
)

"""! \brief
* Chirp config API parameters for TDM-MIMO
"""
cdef rlChirpCfg_t chirpCfgArgs = rlChirpCfg_t(
    chirpStartIdx = 0,
    chirpEndIdx = 0,
    profileId = 0,
    txEnable = 0x00,
    adcStartTimeVar = 0,
    idleTimeVar = 0,
    startFreqVar = 0,
    freqSlopeVar = 0,
)

"""! \brief
* Rx/Tx Channel Configuration
"""
cdef rlChanCfg_t channelCfgArgs = rlChanCfg_t(
    rxChannelEn = 0x0F,      # Enable all 4 RX Channels
    txChannelEn = 0x07,      # Enable all 3 TX Channels
    cascading = 0x02,        # Slave (will be set to 1 for Master)
)

cdef rlAdcBitFormat_t adcBitFmtArgs = rlAdcBitFormat_t(
    b2AdcBits = 2,           # 16-bit ADC
    b2AdcOutFmt = 1,         # Complex values
    b8FullScaleReducFctr = 0,
)

cdef rlAdcOutCfg_t adcOutCfgArgs = rlAdcOutCfg_t(
    fmt = adcBitFmtArgs,
)

cdef rlDevDataFmtCfg_t dataFmtCfgArgs = rlDevDataFmtCfg_t(
    iqSwapSel = 0,           # I first
    chInterleave = 0,        # Interleaved mode
    rxChannelEn = 0xF,       # All RX antenna enabled
    adcFmt = 1,              # Complex
    adcBits = 2,             # 16-bit ADC
)

cdef rlRfLdoBypassCfg_t ldoCfgArgs = rlRfLdoBypassCfg_t(
    ldoBypassEnable = 3,       # RF LDO disabled, PA LDO disabled
    ioSupplyIndicator = 0,
    supplyMonIrDrop = 0,
)

cdef rlLowPowerModeCfg_t lpmCfgArgs = rlLowPowerModeCfg_t(
    lpAdcMode = 0,             # Regular ADC power mode
)

cdef rlRfMiscConf_t miscCfgArgs = rlRfMiscConf_t(
    miscCtl = 1,               # Enable Per chirp phase shifter
)

cdef rlDevDataPathCfg_t datapathCfgArgs = rlDevDataPathCfg_t(
    intfSel = 0,               # CSI2 interface
    transferFmtPkt0 = 1,       # ADC data only
    transferFmtPkt1 = 0,       # Suppress packet 1
)

cdef rlDevDataPathClkCfg_t datapathClkCfgArgs = rlDevDataPathClkCfg_t(
    laneClkCfg = 1,            # DDR Clock
    dataRate = 1,              # 600Mbps
)

cdef rlDevHsiClk_t hsClkCfgArgs = rlDevHsiClk_t(
    hsiClk = 0x09,             # DDR 600Mbps
)

cdef rlDevCsi2Cfg_t csi2LaneCfgArgs = rlDevCsi2Cfg_t(
    lineStartEndDis = 0,       # Enable
    lanePosPolSel = 0x35421,   # Lane configuration
)

"""
TDM-MIMO CHIRP TABLE - EXACTLY MATCHES WINDOWS .LUA FILE
|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
|       | Dev 1 | Dev 1 | Dev 1 | Dev 2 | Dev 2 | Dev 2 | Dev 3 | Dev 3 | Dev 3 | Dev 4 | Dev 4 | Dev 4 |
| Chirp |  TX0  |  TX1  |  TX2  |  TX 0 |  TX1  |  TX2  |  TX0  |  TX1  |  TX2  |  TX0  |  TX1  |  TX2  |
|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
|     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     1 |
|     1 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     1 |     0 |
|     2 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     1 |     0 |     0 |
|     3 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     1 |     0 |     0 |     0 |
|     4 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     1 |     0 |     0 |     0 |     0 |
|     5 |     0 |     0 |     0 |     0 |     0 |     0 |     1 |     0 |     0 |     0 |     0 |     0 |
|     6 |     0 |     0 |     0 |     0 |     0 |     1 |     0 |     0 |     0 |     0 |     0 |     0 |
|     7 |     0 |     0 |     0 |     0 |     1 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |
|     8 |     0 |     0 |     0 |     1 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |
|     9 |     0 |     0 |     1 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |
|    10 |     0 |     1 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |
|    11 |     1 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |     0 |
|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
"""


cdef int8_t is_in_table(uint8_t value, uint8_t[:] table, uint8_t size):
    '''@brief Check if a value is in the table
    @param value Value to look for
    @param table Table to search
    @param size Size of table
    @return Index if found, -1 otherwise
    '''
    cdef uint8_t i
    for i in range(size):
        if table[i] == value:
            return i
    return -1


cpdef uint32_t configureMimoChirp(uint8_t devId, rlChirpCfg_t chirpCfg):
    """@brief TDM-MIMO Chirp configuration
    Configures 12 chirps per device with device-specific TX patterns
    @param devId Device ID (0: master, 1: slave1, 2: slave2, 3: slave3)
    @param chirpCfg Initial chirp configuration
    @return uint32_t Configuration status
    """
    # TDM-MIMO TX table - matches Windows .lua exactly
    # Each device has 3 active chirps (one per TX antenna)
    cdef uint8_t[4][3] chripTxTable=[[11,10,9],[8,7,6],[5,4,3],[2,1,0]]
    
    cdef int status = 0
    cdef uint8_t i
    cdef int8_t txIdx
    
    printf(b"\n[TDM-MIMO] Configuring chirps for Device %u:\n", devId)
    
    for i in range(NUM_CHIRPS):
        txIdx = is_in_table(i, chripTxTable[devId], 3)

        # Update chirp configuration
        chirpCfg.chirpStartIdx = i
        chirpCfg.chirpEndIdx = i
        
        if txIdx < 0:
            # This chirp is inactive for this device
            chirpCfg.txEnable = 0x00
        else:
            # This chirp uses one TX antenna (TX0, TX1, or TX2)
            chirpCfg.txEnable = (1 << txIdx)

        # Configure chirp
        status += MMWL_chirpConfig(createDevMapFromDevId(devId), chirpCfg)

        # Debug output
        if txIdx >= 0:
            printf(b"  Chirp %2u: TX%u ENABLED  ", i, txIdx)
        else:
            printf(b"  Chirp %2u: ALL TX OFF   ", i)
            
        if status == 0:
            printf(b"[OK]\n")
        else:
            printf(b"[FAILED]\n")
            break

    return status


cdef void check(int status, char* success_msg, char* error_msg,
                unsigned char deviceMap, uint8_t is_required):
    """@brief Check status and print messages
    @param status Status value
    @param success_msg Success message
    @param error_msg Error message
    @param deviceMap Device map
    @param is_required Exit on failure if True
    """
    if DEV_ENV:
        printf(b"STATUS %4d | DEV MAP: %2u | ", status, deviceMap)

    if status == RL_RET_CODE_OK:
        if DEV_ENV:
            printf(success_msg)
            printf(b"\n")
        return
    else:
        if DEV_ENV:
            printf(error_msg)
            printf(b"\n")
        
        if is_required != 0:
            exit(status)


cdef int32_t initMaster(rlChanCfg_t channelCfg, rlAdcOutCfg_t adcOutCfg):
    """@brief Initialize Master device (Device 0)"""
    cdef unsigned int masterId = 0
    cdef unsigned int masterMap = 1U << masterId
    cdef int status = 0
    
    printf(b"\n[MASTER INIT] Starting...\n")
    
    # Master cascading mode
    channelCfg.cascading = 1
    
    status += MMWL_DevicePowerUp(masterMap, 1000, 1000)
    check(status,
        b"[MASTER] Power up successful!",
        b"[MASTER] Error: Failed to power up device!", masterMap, TRUE)

    status += MMWL_firmwareDownload(masterMap)
    check(status,
        b"[MASTER] Firmware successfully uploaded!",
        b"[MASTER] Error: Firmware upload failed!", masterMap, TRUE)

    status += MMWL_setDeviceCrcType(masterMap)
    check(status,
        b"[MASTER] CRC type has been set!",
        b"[MASTER] Error: Unable to set CRC type!", masterMap, TRUE)

    status += MMWL_rfEnable(masterMap)
    check(status,
        b"[MASTER] RF successfully enabled!",
        b"[MASTER] Error: Failed to enable master RF", masterMap, TRUE)

    status += MMWL_channelConfig(masterMap, channelCfg.cascading, channelCfg)
    check(status,
        b"[MASTER] Channels successfully configured!",
        b"[MASTER] Error: Channels configuration failed!", masterMap, TRUE)

    status += MMWL_adcOutConfig(masterMap, adcOutCfg)
    check(status,
        b"[MASTER] ADC output format successfully configured!",
        b"[MASTER] Error: ADC output format configuration failed!", masterMap, TRUE)

    check(status,
        b"[MASTER] Init completed with success",
        b"[MASTER] Init completed with error", masterMap, TRUE)
    
    printf(b"[MASTER INIT] Complete!\n")
    return status


cdef int32_t initSlaves(rlChanCfg_t channelCfg, rlAdcOutCfg_t adcOutCfg):
    """@brief Initialize all Slave devices (Devices 1, 2, 3)"""
    cdef int status = 0
    cdef uint8_t slavesMap = (1 << 1) | (1 << 2) | (1 << 3)
    cdef unsigned int slaveMap

    printf(b"\n[SLAVES INIT] Starting...\n")
    
    # Slave cascading mode
    channelCfg.cascading = 2

    # Power up each slave individually
    for slaveId in range(1, 4):
        slaveMap = 1 << slaveId
        printf(b"[SLAVE %u] Powering up...\n", slaveId)
        status += MMWL_DevicePowerUp(slaveMap, 1000, 1000)
        check(status,
            b"[SLAVE] Power up successful!",
            b"[SLAVE] Error: Failed to power up device!", slaveMap, TRUE)

    # Configure all slaves together
    printf(b"[SLAVES] Configuring all slaves together...\n")
    
    status += MMWL_firmwareDownload(slavesMap)
    check(status,
        b"[SLAVES] Firmware successfully uploaded!",
        b"[SLAVES] Error: Firmware upload failed!", slavesMap, TRUE)

    status += MMWL_setDeviceCrcType(slavesMap)
    check(status,
        b"[SLAVES] CRC type has been set!",
        b"[SLAVES] Error: Unable to set CRC type!", slavesMap, TRUE)

    status += MMWL_rfEnable(slavesMap)
    check(status,
        b"[SLAVES] RF successfully enabled!",
        b"[SLAVES] Error: Failed to enable RF", slavesMap, TRUE)

    status += MMWL_channelConfig(slavesMap, channelCfg.cascading, channelCfg)
    check(status,
        b"[SLAVES] Channels successfully configured!",
        b"[SLAVES] Error: Channels configuration failed!", slavesMap, TRUE)

    status += MMWL_adcOutConfig(slavesMap, adcOutCfg)
    check(status,
        b"[SLAVES] ADC output format successfully configured!",
        b"[SLAVES] Error: ADC output format configuration failed!", slavesMap, TRUE)

    check(status,
        b"[SLAVES] Init completed with success",
        b"[SLAVES] Init completed with error", slavesMap, TRUE)
    
    printf(b"[SLAVES INIT] Complete!\n")
    return status


cdef uint32_t configure(devConfig_t config):
    """@brief Complete TDM-MIMO configuration sequence"""
    cdef int status = 0
    cdef int devId = 0
    
    printf(b"\n")
    printf(b"=" * 80)
    printf(b"\n")
    printf(b"TDM-MIMO CASCADE CONFIGURATION\n")
    printf(b"=" * 80)
    printf(b"\n")
    
    # Step 1: Initialize Master and Slaves
    status += initMaster(config.channelCfg, config.adcOutCfg)
    status += initSlaves(config.channelCfg, config.adcOutCfg)

    # Step 2: Configure all devices together
    printf(b"\n[ALL DEVICES] Configuring common parameters...\n")
    
    status += MMWL_RFDeviceConfig(config.deviceMap)
    check(status,
        b"[ALL] RF device configured!",
        b"[ALL] RF device configuration failed!", config.deviceMap, TRUE)

    status += MMWL_ldoBypassConfig(config.deviceMap, config.ldoCfg)
    check(status,
        b"[ALL] LDO Bypass configuration successful!",
        b"[ALL] LDO Bypass configuration failed!", config.deviceMap, TRUE)

    status += MMWL_dataFmtConfig(config.deviceMap, config.dataFmtCfg)
    check(status,
        b"[ALL] Data format configuration successful!",
        b"[ALL] Data format configuration failed!", config.deviceMap, TRUE)

    status += MMWL_lowPowerConfig(config.deviceMap, config.lpmCfg)
    check(status,
        b"[ALL] Low Power Mode configuration successful!",
        b"[ALL] Low Power Mode configuration failed!", config.deviceMap, TRUE)

    status += MMWL_ApllSynthBwConfig(config.deviceMap)
    status += MMWL_setMiscConfig(config.deviceMap, config.miscCfg)
    status += MMWL_rfInit(config.deviceMap)
    check(status,
        b"[ALL] RF successfully initialized!",
        b"[ALL] RF init failed!", config.deviceMap, TRUE)

    status += MMWL_dataPathConfig(config.deviceMap, config.datapathCfg)
    status += MMWL_hsiClockConfig(config.deviceMap, config.datapathClkCfg, config.hsClkCfg)
    status += MMWL_CSI2LaneConfig(config.deviceMap, config.csi2LaneCfg)
    check(status,
        b"[ALL] Datapath configuration successful!",
        b"[ALL] Datapath configuration failed!", config.deviceMap, TRUE)

    # Step 3: Profile configuration
    printf(b"\n[PROFILE CONFIG] Configuring profile...\n")
    status += MMWL_profileConfig(config.deviceMap, config.profileCfg)
    check(status,
        b"[ALL] Profile configuration successful!",
        b"[ALL] Profile configuration failed!", config.deviceMap, TRUE)

    # Step 4: TDM-MIMO Chirp configuration (device-specific)
    printf(b"\n[TDM-MIMO CHIRP CONFIG] Starting...\n")
    for devId in range(4):
        status += configureMimoChirp(devId, config.chirpCfg)

    check(status,
        b"[ALL] TDM-MIMO Chirp configuration successful!",
        b"[ALL] Chirp configuration failed!", config.deviceMap, TRUE)

    # Step 5: Frame configuration with proper trigger modes
    printf(b"\n[FRAME CONFIG] Configuring frames...\n")
    
    # Master frame config with SOFTWARE trigger
    printf(b"[MASTER] Configuring with SOFTWARE trigger (triggerSelect=1)...\n")
    status += MMWL_frameConfig(
        config.masterMap,
        config.frameCfg,          # Uses triggerSelect = 1 (software)
        config.channelCfg,
        config.adcOutCfg,
        config.datapathCfg,
        config.profileCfg
    )
    check(status,
        b"[MASTER] Frame configuration completed!",
        b"[MASTER] Frame configuration failed!", config.masterMap, TRUE)

    # Slaves frame config with HARDWARE trigger
    printf(b"[SLAVES] Configuring with HARDWARE trigger (triggerSelect=2)...\n")
    status += MMWL_frameConfig(
        config.slavesMap,
        config.frameCfgSlave,     # Uses triggerSelect = 2 (hardware)
        config.channelCfg,
        config.adcOutCfg,  
        config.datapathCfg,
        config.profileCfg
    )
    check(status,
        b"[SLAVES] Frame configuration completed!",
        b"[SLAVES] Frame configuration failed!", config.slavesMap, TRUE)

    printf(b"\n")
    printf(b"=" * 80)
    printf(b"\n")
    printf(b"TDM-MIMO CONFIGURATION COMPLETE\n")
    printf(b"=" * 80)
    printf(b"\n\n")
    
    return status


cdef devConfig_t config


cpdef mmw_set_config(dict configdict):
    """@brief Set configuration from Python dictionary
    This function parses the config dict and sets up TDM-MIMO parameters
    """
    global config
    
    # Initialize device map (all 4 devices)
    config.deviceMap = 1|(1<<1)|(1<<2)|(1<<3)
    MMWL_AssignDeviceMap(config.deviceMap, &config.masterMap, &config.slavesMap)
    
    # Initialize with default configs
    config.frameCfg = frameCfgArgs
    config.frameCfgSlave = frameCfgArgs  # Copy for slaves
    config.profileCfg = profileCfgArgs
    config.chirpCfg = chirpCfgArgs
    config.channelCfg = channelCfgArgs
    config.csi2LaneCfg = csi2LaneCfgArgs
    config.datapathCfg = datapathCfgArgs
    config.datapathClkCfg = datapathClkCfgArgs
    config.hsClkCfg = hsClkCfgArgs
    config.ldoCfg = ldoCfgArgs
    config.lpmCfg = lpmCfgArgs
    config.miscCfg = miscCfgArgs

    cdef dict mimo, profile, frame, channel
    
    if "mimo" in configdict:
        mimo = configdict["mimo"]
        
        # [PROFILE CONFIGURATION]
        if "profile" in mimo:
            profile = mimo["profile"]
            
            if "id" in profile:
                config.profileCfg.profileId = <uint16_t>(profile["id"])
                
            if "start_freq" in profile:
                # Convert GHz to register value (1 LSB = 53.644 Hz)
                config.profileCfg.startFreqConst = <uint32_t>(ceil(profile["start_freq"]*1e9/53.644))
                printf(b"[CONFIG] Start frequency: %.2f GHz (reg: %u)\n", 
                       <double>profile["start_freq"], config.profileCfg.startFreqConst)
                
            if "slope" in profile:
                # Convert MHz/us to register value (1 LSB = 48.279 kHz/us)
                config.profileCfg.freqSlopeConst = <int16_t>(ceil(profile["slope"]*1e3/48.279))
                printf(b"[CONFIG] Slope: %.3f MHz/us (reg: %d)\n",
                       <double>profile["slope"], config.profileCfg.freqSlopeConst)
                
            if "idle_time" in profile:
                # Convert us to register value (1 LSB = 10 ns)
                config.profileCfg.idleTimeConst = <uint32_t>(ceil(profile["idle_time"]*1e2))
                
            if "adc_start_time" in profile:
                # Convert us to register value (1 LSB = 10 ns)
                config.profileCfg.adcStartTimeConst = <uint32_t>(ceil(profile["adc_start_time"]*1e2))
                
            if "ramp_end_time" in profile:
                # Convert us to register value (1 LSB = 10 ns)
                config.profileCfg.rampEndTime = <uint32_t>(ceil(profile["ramp_end_time"]*1e2))
                
            if "txStartTimeUSec" in profile:
                # Convert us to register value (1 LSB = 10 ns)
                config.profileCfg.txStartTime = <uint16_t>(ceil(profile["txStartTimeUSec"]*1e2))
                
            if "adc_samples" in profile:
                config.profileCfg.numAdcSamples = <uint16_t>(profile["adc_samples"])
                printf(b"[CONFIG] ADC samples: %u\n", config.profileCfg.numAdcSamples)
                
            if "sample_freq" in profile:
                config.profileCfg.digOutSampleRate = <uint16_t>(profile["sample_freq"])
                
            if "rx_gain" in profile:
                config.profileCfg.rxGain = <uint16_t>(profile["rx_gain"])
                
            if "hpfCornerFreq1" in profile:
                config.profileCfg.hpfCornerFreq1 = <uint8_t>(profile["hpfCornerFreq1"])
                
            if "hpfCornerFreq2" in profile:
                config.profileCfg.hpfCornerFreq2 = <uint8_t>(profile["hpfCornerFreq2"])
            
        # [FRAME CONFIGURATION]
        if "frame" in mimo:
            frame = mimo["frame"]
            
            if "nframes_master" in frame:
                config.frameCfg.numFrames = <uint16_t>(frame["nframes_master"])
                printf(b"[CONFIG] Master frames: %u\n", config.frameCfg.numFrames)
                
            if "nframes_slave" in frame:
                config.frameCfgSlave.numFrames = <uint16_t>(frame["nframes_slave"])
                printf(b"[CONFIG] Slave frames: %u\n", config.frameCfgSlave.numFrames)
            else:
                # If not specified, use same as master
                config.frameCfgSlave.numFrames = config.frameCfg.numFrames
                
            if "nchirp_loops" in frame:
                config.frameCfg.numLoops = <uint16_t>(frame["nchirp_loops"])
                config.frameCfgSlave.numLoops = <uint16_t>(frame["nchirp_loops"])
                printf(b"[CONFIG] Chirp loops per frame: %u\n", config.frameCfg.numLoops)
                
            if "Inter_Frame_Interval" in frame:
                # Convert ms to register value (1 LSB = 5 ns)
                config.frameCfg.framePeriodicity = <uint32_t>(ceil(frame["Inter_Frame_Interval"]*2e5))
                config.frameCfgSlave.framePeriodicity = config.frameCfg.framePeriodicity
                printf(b"[CONFIG] Frame interval: %u ms (reg: %u)\n",
                       <uint32_t>frame["Inter_Frame_Interval"], config.frameCfg.framePeriodicity)
            
            # CRITICAL: Set trigger modes for TDM-MIMO
            if "trigger_mode_master" in frame:
                config.frameCfg.triggerSelect = <uint16_t>(frame["trigger_mode_master"])
                printf(b"[CONFIG] Master trigger mode: %u (1=SW, 2=HW)\n", 
                       config.frameCfg.triggerSelect)
            else:
                config.frameCfg.triggerSelect = 1  # Default: Software trigger
                printf(b"[CONFIG] Master trigger mode: 1 (Software - default)\n")
                
            if "trigger_mode_slave" in frame:
                config.frameCfgSlave.triggerSelect = <uint16_t>(frame["trigger_mode_slave"])
                printf(b"[CONFIG] Slave trigger mode: %u (1=SW, 2=HW)\n",
                       config.frameCfgSlave.triggerSelect)
            else:
                config.frameCfgSlave.triggerSelect = 2  # Default: Hardware trigger
                printf(b"[CONFIG] Slave trigger mode: 2 (Hardware - default)\n")
        
        # [CHANNEL CONFIGURATION]
        if "channel" in mimo:
            channel = mimo["channel"]
            
            if "rxChannelEn" in channel:
                config.channelCfg.rxChannelEn = <uint16_t>(channel["rxChannelEn"])
                
            if "txChannelEn" in channel:
                config.channelCfg.txChannelEn = <uint16_t>(channel["txChannelEn"])
    
    # Update dependent parameters
    config.frameCfg.numAdcSamples = 2 * config.profileCfg.numAdcSamples  # Complex samples
    config.frameCfgSlave.numAdcSamples = config.frameCfg.numAdcSamples
    
    config.dataFmtCfg.rxChannelEn = config.channelCfg.rxChannelEn
    config.dataFmtCfg.adcBits = adcOutCfgArgs.fmt.b2AdcBits
    config.dataFmtCfg.adcFmt = adcOutCfgArgs.fmt.b2AdcOutFmt
    
    printf(b"\n[CONFIG] Configuration parsing complete!\n")
    return 0


cpdef int mmw_init(str ip_addr="192.168.33.180", int port=5001):
    """@brief Initialize mmWave cascade system
    @param ip_addr TDA IP address
    @param port TDA port number
    @return Status code
    """
    cdef int status = 0
    cdef bytes ip_addr_bytes = ip_addr.encode('utf-8')
    
    printf(b"\n[INIT] Connecting to TDA at %s:%d\n", <char*>ip_addr_bytes, port)
    
    status = MMWL_TDAInit(ip_addr_bytes, port, config.deviceMap)
    check(status,
        b"[TDA] Connected successfully!",
        b"[TDA] Connection failed!", 32, TRUE)

    # Run complete TDM-MIMO configuration
    configure(config)
    
    return status


cpdef int mmw_arming_tda(str capture_path):
    """@brief Arm TDA for recording
    @param capture_path Directory name for captured data
    @return Status code
    """
    cdef int status = 0
    cdef bytes capture_path_bytes = f"/mnt/ssd/{capture_path}".encode('utf-8')
    
    cdef rlTdaArmCfg_t tdaCfg = rlTdaArmCfg_t(
        captureDirectory = capture_path_bytes,
        framePeriodicity = (config.frameCfg.framePeriodicity * 5)//(1000 * 1000),  # Convert to ms
        numberOfFilesToAllocate = 0,
        numberOfFramesToCapture = 0,  # 0 = capture all frames
        dataPacking = 0,  # 0: 16-bit | 1: 12-bit
    )
    
    status = MMWL_ArmingTDA(tdaCfg)
    check(status,
        b"[TDA] Armed for recording",
        b"[TDA] Arming failed!", 32, 0)
    
    return status


cpdef int mmw_start_frame():
    """@brief Start frame acquisition
    This triggers the cascade: Slaves start on hardware trigger, Master starts on software trigger
    @return Status code
    """
    cdef int status = 0
    
    status += MMWL_StartFrame(config.deviceMap)
    check(status,
        b"[FRAME] Started (Master SW trigger -> Slaves HW trigger)",
        b"[FRAME] Failed to start!", config.deviceMap, 0)
    
    return status


cpdef int mmw_stop_frame():
    """@brief Stop frame acquisition
    @return Status code
    """
    cdef int status = 0
    
    status += MMWL_StopFrame(config.deviceMap)
    check(status,
        b"[FRAME] Stopped",
        b"[FRAME] Failed to stop!", config.deviceMap, 0)
    
    return status


cpdef int mmw_dearming_tda():
    """@brief De-arm TDA (stop recording)
    @return Status code
    """
    cdef int status = 0
    
    status = MMWL_DeArmingTDA()
    check(status,
        b"[TDA] De-armed (recording stopped)",
        b"[TDA] Failed to de-arm!", 32, 0)
    
    return status