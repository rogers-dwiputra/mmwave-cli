/**
 * @file mimo.c
 * @author AMOUSSOU Z. Kenneth (www.gitlab.com/azinke)
 * @brief MMWave Radar configuration and control tool
 *
 * @note: Only MIMO setup is supported for now
 *
 * The MMWCAS-RF-EVM revision E has AWR2243 radar chips
 *
 * Approximate default configuration (generated uing mmWave Sensing Estimator):
 *
 *  Max Detectable Range  : ~80m
 *  Range resolution      : ~31cm
 *  May Velocity          : ~6.49 km/h
 *  Velocity resolution   : ~0.4 km/h
 *
 * @version 0.1
 * @date 2022-07-21
 *
 * @copyright Copyright (c) 2022
 *
 */
#include "mimo.h"
#include "toml/config.h"
#include <time.h>
#include <sys/time.h>
#include <pthread.h>
#include <semaphore.h>

/******************************
 *      CONFIGURATIONS
 ******************************/
// Global variable to store IP address for logging
static unsigned char g_ip_addr[32] = {0};
/** Profile config */
const rlProfileCfg_t profileCfgArgs = {
  .profileId = 0,
  .pfVcoSelect = 0x02,
  .startFreqConst = 1434000000,   // 77GHz | 1 LSB = 53.644 Hz
  .freqSlopeConst = 518,          // 15.0148 Mhz/us | 1LSB = 48.279 kHz/uS
  .idleTimeConst = 700,           // 5us  | 1LSB = 10ns
  .adcStartTimeConst = 435,       // 6us  | 1LSB = 10ns
  .rampEndTime = 6897,            // 40us | 1LSB = 10ns
  .txOutPowerBackoffCode = 0x0,
  .txPhaseShifter = 0x0,
  .txStartTime = 0x0,             // 0us | 1LSB = 10ns
  .numAdcSamples = 512,           // 256 ADC samples per chirp
  .digOutSampleRate = 8000,      // 8000 ksps (8 MHz) | 1LSB = 1 ksps
  .hpfCornerFreq1 = 0x0,          // 175kHz
  .hpfCornerFreq2 = 0x0,          // 350kHz
  .rxGain = 48,                   // 48 dB | 1LSB = 1dB
};

/** Frame config */
const rlFrameCfg_t frameCfgArgs = {
  .chirpStartIdx = 0,
  .chirpEndIdx = 11,
  .numFrames = 0,                 // (0 for infinite)
  .numLoops = 10,
  .numAdcSamples = 2 * 256,       // Complex samples (for I and Q siganls)
  .frameTriggerDelay = 0x0,
  .framePeriodicity = 20000000,   // 100ms | 1LSB = 5ns
};

/** Chirps config */
rlChirpCfg_t chirpCfgArgs = {
  .chirpStartIdx = 0,
  .chirpEndIdx = 0,
  .profileId = 0,
  .txEnable = 0x00,
  .adcStartTimeVar = 0,
  .idleTimeVar = 0,
  .startFreqVar = 0,
  .freqSlopeVar = 0,
};

/** Channel config */
rlChanCfg_t channelCfgArgs = {
  .rxChannelEn = 0x0F,      // Enable all 4 RX Channels
  .txChannelEn = 0x07,      // Enable all 3 TX Channels
  .cascading = 0x02,        // Slave
};

/** ADC output config */
rlAdcOutCfg_t adcOutCfgArgs = {
  .fmt = {
    .b2AdcBits = 2,           // 16-bit ADC
    .b2AdcOutFmt = 1,         // Complex values
    .b8FullScaleReducFctr = 0,
  }
};

/** Data format config */
rlDevDataFmtCfg_t dataFmtCfgArgs = {
  .iqSwapSel = 0,           // I first
  .chInterleave = 0,        // Interleaved mode
  .rxChannelEn = 0xF,       // All RX antenna enabled
  .adcFmt = 1,              // Complex
  .adcBits = 2,             // 16-bit ADC
};

/** LDO Bypass config */
rlRfLdoBypassCfg_t ldoCfgArgs = {
  .ldoBypassEnable = 3,       // RF LDO disabled, PA LDO disabled
  .ioSupplyIndicator = 0,
  .supplyMonIrDrop = 0,
};

/** Low Power Mode config */
rlLowPowerModeCfg_t lpmCfgArgs = {
  .lpAdcMode = 0,             // Regular ADC power mode
};

/** Miscellaneous config */
rlRfMiscConf_t miscCfgArgs = {
  .miscCtl = 1,               // Enable Per chirp phase shifter
};

/** Datapath config */
rlDevDataPathCfg_t datapathCfgArgs = {
  .intfSel = 0,               // CSI2 intrface
  .transferFmtPkt0 = 1,       // ADC data only
  .transferFmtPkt1 = 0,       // Suppress packet 1
};

/** Datapath clock config */
rlDevDataPathClkCfg_t datapathClkCfgArgs = {
  .laneClkCfg = 1,            // DDR Clock
  .dataRate = 1,              // 600Mbps
};

/** High speed clock config */
rlDevHsiClk_t hsClkCfgArgs = {
  .hsiClk = 0x09,             // DDR 600Mbps
};

/** CSI2 config */
rlDevCsi2Cfg_t csi2LaneCfgArgs = {
  .lineStartEndDis = 0,       // Enable
  .lanePosPolSel = 0x35421,   // 0b 0011 0101 0100 0010 0001,
};



/*
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
*/

typedef struct {
    char src_path[256];
    char dst_path[256];
    int capture_id;
} transfer_task_t;

// Thread for SCP transfer
void* scp_transfer_thread(void* arg) {
    transfer_task_t* task = (transfer_task_t*)arg;
    
    char cmd[512];
    snprintf(cmd, sizeof(cmd),
        "scp -O -oHostKeyAlgorithms=+ssh-rsa "
        "-oPubkeyAcceptedAlgorithms=+ssh-rsa "
        "-r root@192.168.33.180:%s %s &",
        task->src_path, task->dst_path);
    
    printf("[TRANSFER %d] Starting: %s\n", task->capture_id, cmd);
    int ret = system(cmd);
    printf("[TRANSFER %d] Completed with status: %d\n", task->capture_id, ret);
    
    free(task);
    return NULL;
}

// Non-blocking transfer
int start_async_transfer(const char* capture_dir, int capture_id) {
    transfer_task_t* task = malloc(sizeof(transfer_task_t));
    if (!task) return -1;
    
    snprintf(task->src_path, sizeof(task->src_path), 
             "/mnt/ssd/%s", capture_dir);
    snprintf(task->dst_path, sizeof(task->dst_path),
             "~/mmwave-cli/PostProc/%s", capture_dir);
    task->capture_id = capture_id;
    
    pthread_t thread;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    
    if (pthread_create(&thread, &attr, scp_transfer_thread, task) != 0) {
        free(task);
        return -1;
    }
    
    pthread_attr_destroy(&attr);
    return 0;
}

/**
 * @brief Get current timestamp string
 * 
 * @param buffer Buffer to store the timestamp string
 * @param size Size of the buffer
 */
void get_timestamp(char *buffer, size_t size) {
  struct timeval tv;
  struct tm *tm_info;
  
  gettimeofday(&tv, NULL);
  tm_info = localtime(&tv.tv_sec);
  
  // Format: YYYY-MM-DD HH:MM:SS.mmm
  strftime(buffer, size, "%Y-%m-%d %H:%M:%S", tm_info);
  sprintf(buffer + strlen(buffer), ".%03ld", tv.tv_usec / 1000);
}

/**
 * @brief Check if a value is in the table provided in argument
 *
 * @param value Value to look for in the table
 * @param table Table defining the search context
 * @param size Size of the table
 * @return int8_t
 *      Return the index where the match has been found. -1 if not found
 */
int8_t is_in_table(uint8_t value, uint8_t *table, uint8_t size) {
  for (uint8_t i = 0; i < size; i++) {
    if (table[i] == value) return i;
  }
  return -1;
}


/**
 * @brief MIMO Chirp configuration
 *
 * @param devId Device ID (0: master, 1: slave1, 2: slave2, 3: slave3)
 * @param chirpCfg Initital chirp configuration
 * @return uint32_t Configuration status
 */
uint32_t configureMimoChirp(uint8_t devId, rlChirpCfg_t chirpCfg) {
  const uint8_t chripTxTable [4][3] = {
    {11, 10, 9},   // Dev1 - Master
    {8, 7, 6},     // Dev2
    {5, 4, 3},     // Dev3
    {2, 1, 0},     // Dev4
  };
  int status = 0;

  for (uint8_t i = 0; i < NUM_CHIRPS; i++) {
    int8_t txIdx = is_in_table(i, chripTxTable[devId], 3);

    // Update chirp config
    chirpCfg.chirpStartIdx = i;
    chirpCfg.chirpEndIdx = i;
    if (txIdx < 0) chirpCfg.txEnable = 0x00;
    else chirpCfg.txEnable = (1 << txIdx);
    status += MMWL_chirpConfig(createDevMapFromDevId(devId), chirpCfg);
    DEBUG_PRINT("[CHIRP CONFIG] dev %u, chirp idx %u, status: %d\n", devId, i, status);
    if (status != 0) {
      DEBUG_PRINT("Configuration of chirp %d failed!\n", i);
      break;
    }
  }
  return status;
}

/**
 * @brief Check status and print error or success message
 *
 * @param status Status value returned by a function
 * @param success_msg Success message to print when status is 0
 * @param error_msg Error message to print in case of error
 * @param deviceMap Device map the check if related to
 * @param is_required Indicates if the checking stage is required. if so,
 *                    the program exits in case of failure.
 * @return uint32_t Configuration status
 *
 * @note: Status is considered successful when the status integer is 0.
 * Any other value is considered a failure.
 */
void check(int status, const char *success_msg, const char *error_msg,
      unsigned char deviceMap, uint8_t is_required) {
#if DEV_ENV
  char timestamp[32];
  get_timestamp(timestamp, sizeof(timestamp));
  printf("[%s] [IP: %s] STATUS %4d | DEV MAP: %2u | ", timestamp, g_ip_addr, status, deviceMap);
#endif
  if (status == RL_RET_CODE_OK) {
#if DEV_ENV
    printf(CGREEN);
    printf(success_msg);
    printf(CRESET);
    printf("\n");
#endif
    return;
  } else {
#if DEV_ENV
    printf(CRED);
    printf(error_msg);
    printf(CRESET);
    printf("\n");
#endif
    if (is_required != 0) exit(status);
  }
}


int32_t initMaster(rlChanCfg_t channelCfg, rlAdcOutCfg_t adcOutCfg) {
  const unsigned int masterId = 0;
  const unsigned int masterMap = 1 << masterId;
  int status = 0;

  // master chip
  channelCfg.cascading = 1;

  status += MMWL_DevicePowerUp(masterMap, 1000, 1000);
  check(status,
    "[MASTER] Power up successful!",
    "[MASTER] Error: Failed to power up device!", masterMap, TRUE);

  status += MMWL_firmwareDownload(masterMap);
  check(status,
    "[MASTER] Firmware successfully uploaded!",
    "[MASTER] Error: Firmware upload failed!", masterMap, TRUE);

  status += MMWL_setDeviceCrcType(masterMap);
  check(status,
    "[MASTER] CRC type has been set!",
    "[MASTER] Error: Unable to set CRC type!", masterMap, TRUE);

  status += MMWL_rfEnable(masterMap);
  check(status,
    "[MASTER] RF successfully enabled!",
    "[MASTER] Error: Failed to enable master RF", masterMap, TRUE);

  status += MMWL_channelConfig(masterMap, channelCfg.cascading, channelCfg);
  check(status,
    "[MASTER] Channels successfully configured!",
    "[MASTER] Error: Channels configuration failed!", masterMap, TRUE);

  status += MMWL_adcOutConfig(masterMap, adcOutCfg);
  check(status,
    "[MASTER] ADC output format successfully configured!",
    "[MASTER] Error: ADC output format configuration failed!", masterMap, TRUE);

  check(status,
    "[MASTER] Init completed with sucess\n",
    "[MASTER] Init completed with error", masterMap, TRUE);
  return status;
}


int32_t initSlaves(rlChanCfg_t channelCfg, rlAdcOutCfg_t adcOutCfg) {
  int status = 0;
  uint8_t slavesMap = (1 << 1) | (1 << 2) | (1 << 3);

  // slave chip
  channelCfg.cascading = 2;

  for (uint8_t slaveId = 1; slaveId < 4; slaveId++) {
    unsigned int slaveMap = 1 << slaveId;

    status += MMWL_DevicePowerUp(slaveMap, 1000, 1000);
    check(status,
      "[SLAVE] Power up successful!",
      "[SLAVE] Error: Failed to power up device!", slaveMap, TRUE);
  }

  //Config of all slaves together
  status += MMWL_firmwareDownload(slavesMap);
  check(status,
    "[SLAVE] Firmware successfully uploaded!",
    "[SLAVE] Error: Firmware upload failed!", slavesMap, TRUE);

  status += MMWL_setDeviceCrcType(slavesMap);
  check(status,
    "[SLAVE] CRC type has been set!",
    "[SLAVE] Error: Unable to set CRC type!", slavesMap, TRUE);

  status += MMWL_rfEnable(slavesMap);
  check(status,
    "[SLAVE] RF successfully enabled!",
    "[SLAVE] Error: Failed to enable master RF", slavesMap, TRUE);

  status += MMWL_channelConfig(slavesMap, channelCfg.cascading, channelCfg);
  check(status,
    "[SLAVE] Channels successfully configured!",
    "[SLAVE] Error: Channels configuration failed!", slavesMap, TRUE);

  status += MMWL_adcOutConfig(slavesMap, adcOutCfg);
  check(status,
    "[SLAVE] ADC output format successfully configured!",
    "[SLAVE] Error: ADC output format configuration failed!", slavesMap, TRUE);

  check(status,
    "[SLAVE] Init completed with sucess\n",
    "[SLAVE] Init completed with error", slavesMap, TRUE);
  return status;
}


uint32_t configure (devConfig_t config) {
  int status = 0;
  status += initMaster(config.channelCfg, config.adcOutCfg);
  status += initSlaves(config.channelCfg, config.adcOutCfg);

  status += MMWL_RFDeviceConfig(config.deviceMap);
  check(status,
    "[ALL] RF deivce configured!",
    "[ALL] RF device configuration failed!", config.deviceMap, TRUE);

  status += MMWL_ldoBypassConfig(config.deviceMap, config.ldoCfg);
  check(status,
    "[ALL] LDO Bypass configuration successful!",
    "[ALL] LDO Bypass configuration failed!", config.deviceMap, TRUE);

  status += MMWL_dataFmtConfig(config.deviceMap, config.dataFmtCfg);
  check(status,
    "[ALL] Data format configuration successful!",
    "[ALL] Data format configuration failed!", config.deviceMap, TRUE);

  status += MMWL_lowPowerConfig(config.deviceMap, config.lpmCfg);
  check(status,
    "[ALL] Low Power Mode configuration successful!",
    "[ALL] Low Power Mode configuration failed!", config.deviceMap, TRUE);

  status += MMWL_ApllSynthBwConfig(config.deviceMap);
  status += MMWL_setMiscConfig(config.deviceMap, config.miscCfg);
  status += MMWL_rfInit(config.deviceMap);
  check(status,
    "[ALL] RF successfully initialized!",
    "[ALL] RF init failed!", config.deviceMap, TRUE);

  status += MMWL_dataPathConfig(config.deviceMap, config.datapathCfg);
  status += MMWL_hsiClockConfig(config.deviceMap, config.datapathClkCfg, config.hsClkCfg);
  status += MMWL_CSI2LaneConfig(config.deviceMap, config.csi2LaneCfg);
  check(status,
    "[ALL] Datapath configuration successful!",
    "[ALL] Datapath configuration failed!", config.deviceMap, TRUE);

  status += MMWL_profileConfig(config.deviceMap, config.profileCfg);
  check(status,
    "[ALL] Profile configuration successful!",
    "[ALL] Profile configuration failed!", config.deviceMap, TRUE);

  // MIMO Chirp configuration
  for (uint8_t devId = 0; devId < 4; devId++) {
    status += configureMimoChirp(devId, config.chirpCfg);
  }
  check(status,
    "[ALL] Chirp configuration successful!",
    "[ALL] Chirp configuration failed!", config.deviceMap, TRUE);

  // Master frame config.
  status += MMWL_frameConfig(
    config.masterMap,
    config.frameCfg,
    config.channelCfg,
    config.adcOutCfg,
    config.datapathCfg,
    config.profileCfg
  );
  check(status,
    "[MASTER] Frame configuration completed!",
    "[MASTER] Frame configuration failed!", config.masterMap, TRUE);

  // Slaves frame config
  status += MMWL_frameConfig(
    config.slavesMap,
    config.frameCfg,
    config.channelCfg,
    config.adcOutCfg,
    config.datapathCfg,
    config.profileCfg
  );
  check(status,
    "[SLAVE] Frame configuration completed!",
    "[SLAVE] Frame configuration failed!", config.slavesMap, TRUE);

  check(status,
    "[MIMO] Configuration completed!\n",
    "[MIMO] Configuration completed with error!", config.deviceMap, TRUE);
}


/**
 * @brief Routine to close trace file
 * 
 */
FILE* rls_traceF = NULL;
void CloseTraceFile() {
  if (rls_traceF != NULL) {
    fclose(rls_traceF);
    rls_traceF = NULL;
  }
}

// Pointer to the CLI option parser
parser_t *g_parser = NULL;

/**
 * Print program version
 */
void print_version() {
  printf(PROG_NAME " version " PROG_VERSION ", " PROG_COPYRIGHT "\n");
  exit(0);
}

/**
 * @brief Print CLI options help and exit
 */
void help() {
  print_help(g_parser);
  exit(0);
}

/**
 * @brief Free the parser to cleanup any dynamically allocated memory
 */
void cleanup() {
  free_parser(g_parser);
}

/**
 * @brief Called when the user presses CTRL+C
 *
 * This aim to explicitly call the exit function so that
 * dynamically allocated memory could be freed
 */
void signal_handler () {
  exit(1);
}

/**
 * @brief Helper function to convert hex string to integer
 */
static unsigned int hex_string_to_int(const char* hex_str) {
    unsigned int value = 0;
    sscanf(hex_str, "0x%x", &value);
    return value;
}

/**
 * @brief Export device configuration to mmwave.json format
 * 
 * @param config Device configuration structure
 * @param filename Output JSON filename
 * @param num_devices Number of cascade devices (1-4)
 * @return int 0 on success, -1 on failure
 */
int export_config_to_json(devConfig_t config, const char* filename, int num_devices) {
    FILE* fp = fopen(filename, "w");
    if (fp == NULL) {
        printf("Error: Cannot create file %s\n", filename);
        return -1;
    }

    // Get current timestamp
    time_t now = time(NULL);
    struct tm* tm_info = localtime(&now);
    char timestamp[64];
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%dT%H:%M:%S", tm_info);

    // Start JSON
    fprintf(fp, "{\n");
    
    // Config Generator
    fprintf(fp, "  \"configGenerator\": {\n");
    fprintf(fp, "    \"createdBy\": \"mmwave-cli\",\n");
    fprintf(fp, "    \"createdOn\": \"%s+09:00\",\n", timestamp);
    fprintf(fp, "    \"isConfigIntermediate\": 1\n");
    fprintf(fp, "  },\n");

    // Versions
    fprintf(fp, "  \"currentVersion\": {\n");
    fprintf(fp, "    \"jsonCfgVersion\": {\n");
    fprintf(fp, "      \"major\": 0,\n");
    fprintf(fp, "      \"minor\": 4,\n");
    fprintf(fp, "      \"patch\": 0\n");
    fprintf(fp, "    },\n");
    fprintf(fp, "    \"DFPVersion\": {\n");
    fprintf(fp, "      \"major\": 2,\n");
    fprintf(fp, "      \"minor\": 2,\n");
    fprintf(fp, "      \"patch\": 0\n");
    fprintf(fp, "    },\n");
    fprintf(fp, "    \"SDKVersion\": {\n");
    fprintf(fp, "      \"major\": 3,\n");
    fprintf(fp, "      \"minor\": 3,\n");
    fprintf(fp, "      \"patch\": 0\n");
    fprintf(fp, "    },\n");
    fprintf(fp, "    \"mmwavelinkVersion\": {\n");
    fprintf(fp, "      \"major\": 2,\n");
    fprintf(fp, "      \"minor\": 2,\n");
    fprintf(fp, "      \"patch\": 0\n");
    fprintf(fp, "    }\n");
    fprintf(fp, "  },\n");

    // Last Backward Compatible Version
    fprintf(fp, "  \"lastBackwardCompatibleVersion\": {\n");
    fprintf(fp, "    \"DFPVersion\": {\n");
    fprintf(fp, "      \"major\": 2,\n");
    fprintf(fp, "      \"minor\": 1,\n");
    fprintf(fp, "      \"patch\": 0\n");
    fprintf(fp, "    },\n");
    fprintf(fp, "    \"SDKVersion\": {\n");
    fprintf(fp, "      \"major\": 3,\n");
    fprintf(fp, "      \"minor\": 0,\n");
    fprintf(fp, "      \"patch\": 0\n");
    fprintf(fp, "    },\n");
    fprintf(fp, "    \"mmwavelinkVersion\": {\n");
    fprintf(fp, "      \"major\": 2,\n");
    fprintf(fp, "      \"minor\": 1,\n");
    fprintf(fp, "      \"patch\": 0\n");
    fprintf(fp, "    }\n");
    fprintf(fp, "  },\n");

    // Regulatory Restrictions
    fprintf(fp, "  \"regulatoryRestrictions\": {\n");
    fprintf(fp, "    \"frequencyRangeBegin_GHz\": 77,\n");
    fprintf(fp, "    \"frequencyRangeEnd_GHz\": 81,\n");
    fprintf(fp, "    \"maxBandwidthAllowed_MHz\": 4000,\n");
    fprintf(fp, "    \"maxTransmitPowerAllowed_dBm\": 12\n");
    fprintf(fp, "  },\n");

    // System Config
    fprintf(fp, "  \"systemConfig\": {\n");
    fprintf(fp, "    \"summary\": \"Configuration exported from mmwave-cli\",\n");
    fprintf(fp, "    \"sceneParameters\": {\n");
    fprintf(fp, "      \"ambientTemperature_degC\": 20,\n");
    fprintf(fp, "      \"maxDetectableRange_m\": 10,\n");
    fprintf(fp, "      \"rangeResolution_cm\": 5,\n");
    fprintf(fp, "      \"maxVelocity_kmph\": 26,\n");
    fprintf(fp, "      \"velocityResolution_kmph\": 2,\n");
    fprintf(fp, "      \"measurementRate\": 10,\n");
    fprintf(fp, "      \"typicalDetectedObjectRCS\": 1.0\n");
    fprintf(fp, "    }\n");
    fprintf(fp, "  },\n");

    // mmWave Devices Array
    fprintf(fp, "  \"mmWaveDevices\": [\n");

    // Calculate start frequency in GHz
    float startFreq_GHz = (config.profileCfg.startFreqConst * 53.6441803) / (1000.0 * 1000.0 * 1000.0);
    float freqSlope_MHz_usec = (config.profileCfg.freqSlopeConst * 48.2797623) / 1000.0;
    float idleTime_usec = config.profileCfg.idleTimeConst * 0.01; // 1 LSB = 10ns
    float adcStartTime_usec = config.profileCfg.adcStartTimeConst * 0.01;
    float rampEndTime_usec = config.profileCfg.rampEndTime * 0.01;
    float txStartTime_usec = config.profileCfg.txStartTime * 0.01;
    float framePeriodicity_msec = (config.frameCfg.framePeriodicity * 5.0) / (1000.0 * 1000.0);

    // Loop through devices
    for (int devId = 0; devId < num_devices; devId++) {
        fprintf(fp, "    {\n");
        fprintf(fp, "      \"mmWaveDeviceId\": %d,\n", devId);
        fprintf(fp, "      \"rfConfig\": {\n");
        fprintf(fp, "        \"waveformType\": \"legacyFrameChirp\",\n");
        fprintf(fp, "        \"MIMOScheme\": \"TDM\",\n");
        fprintf(fp, "        \"rlCalibrationDataFile\": \"\",\n");

        // Channel Config
        fprintf(fp, "        \"rlChanCfg_t\": {\n");
        fprintf(fp, "          \"rxChannelEn\": \"0x%X\",\n", config.channelCfg.rxChannelEn);
        fprintf(fp, "          \"txChannelEn\": \"0x%X\",\n", config.channelCfg.txChannelEn);
        fprintf(fp, "          \"cascading\": %d,\n", devId == 0 ? 1 : 2); // Master=1, Slave=2
        fprintf(fp, "          \"cascadingPinoutCfg\": \"0x0\"\n");
        fprintf(fp, "        },\n");

        // ADC Out Config
        fprintf(fp, "        \"rlAdcOutCfg_t\": {\n");
        fprintf(fp, "          \"fmt\": {\n");
        fprintf(fp, "            \"b2AdcBits\": %d,\n", config.adcOutCfg.fmt.b2AdcBits);
        fprintf(fp, "            \"b8FullScaleReducFctr\": %d,\n", config.adcOutCfg.fmt.b8FullScaleReducFctr);
        fprintf(fp, "            \"b2AdcOutFmt\": %d\n", config.adcOutCfg.fmt.b2AdcOutFmt);
        fprintf(fp, "          }\n");
        fprintf(fp, "        },\n");

        // Low Power Mode Config
        fprintf(fp, "        \"rlLowPowerModeCfg_t\": {\n");
        fprintf(fp, "          \"lpAdcMode\": %d\n", config.lpmCfg.lpAdcMode);
        fprintf(fp, "        },\n");

        // Profile Config
        fprintf(fp, "        \"rlProfiles\": [\n");
        fprintf(fp, "          {\n");
        fprintf(fp, "            \"rlProfileCfg_t\": {\n");
        fprintf(fp, "              \"profileId\": %d,\n", config.profileCfg.profileId);
        fprintf(fp, "              \"pfVcoSelect\": \"0x%X\",\n", config.profileCfg.pfVcoSelect);
        fprintf(fp, "              \"pfCalLutUpdate\": \"0x0\",\n");
        fprintf(fp, "              \"startFreqConst_GHz\": %.16f,\n", startFreq_GHz);
        fprintf(fp, "              \"idleTimeConst_usec\": %.1f,\n", idleTime_usec);
        fprintf(fp, "              \"adcStartTimeConst_usec\": %.16f,\n", adcStartTime_usec);
        fprintf(fp, "              \"rampEndTime_usec\": %.15f,\n", rampEndTime_usec);
        fprintf(fp, "              \"txOutPowerBackoffCode\": \"0x%X\",\n", config.profileCfg.txOutPowerBackoffCode);
        fprintf(fp, "              \"txPhaseShifter\": \"0x%X\",\n", config.profileCfg.txPhaseShifter);
        fprintf(fp, "              \"freqSlopeConst_MHz_usec\": %.15f,\n", freqSlope_MHz_usec);
        fprintf(fp, "              \"txStartTime_usec\": %.1f,\n", txStartTime_usec);
        fprintf(fp, "              \"numAdcSamples\": %d,\n", config.profileCfg.numAdcSamples);
        fprintf(fp, "              \"digOutSampleRate\": %.1f,\n", (float)config.profileCfg.digOutSampleRate);
        fprintf(fp, "              \"hpfCornerFreq1\": %d,\n", config.profileCfg.hpfCornerFreq1);
        fprintf(fp, "              \"hpfCornerFreq2\": %d,\n", config.profileCfg.hpfCornerFreq2);
        fprintf(fp, "              \"rxGain_dB\": \"0x%X\"\n", config.profileCfg.rxGain);
        fprintf(fp, "            }\n");
        fprintf(fp, "          }\n");
        fprintf(fp, "        ],\n");

        // Chirp Config - 12 chirps for MIMO
        fprintf(fp, "        \"rlChirps\": [\n");
        for (int chirpIdx = 0; chirpIdx < NUM_CHIRPS; chirpIdx++) {
            // Determine TX enable based on device and chirp index
            const uint8_t chirpTxTable[4][3] = {
                {11, 10, 9},   // Dev0 - Master
                {8, 7, 6},     // Dev1
                {5, 4, 3},     // Dev2
                {2, 1, 0},     // Dev3
            };
            
            uint8_t txEnable = 0x0;
            for (int tx = 0; tx < 3; tx++) {
                if (chirpTxTable[devId][tx] == chirpIdx) {
                    txEnable = (1 << tx);
                    break;
                }
            }

            fprintf(fp, "          {\n");
            fprintf(fp, "            \"rlChirpCfg_t\": {\n");
            fprintf(fp, "              \"chirpStartIdx\": %d,\n", chirpIdx);
            fprintf(fp, "              \"chirpEndIdx\": %d,\n", chirpIdx);
            fprintf(fp, "              \"profileId\": 0,\n");
            fprintf(fp, "              \"startFreqVar_MHz\": 0.0,\n");
            fprintf(fp, "              \"freqSlopeVar_KHz_usec\": 0.0,\n");
            fprintf(fp, "              \"idleTimeVar_usec\": 0.0,\n");
            fprintf(fp, "              \"adcStartTimeVar_usec\": 0.0,\n");
            fprintf(fp, "              \"txEnable\": \"0x%X\"\n", txEnable);
            fprintf(fp, "            }\n");
            fprintf(fp, "          }%s\n", (chirpIdx < NUM_CHIRPS - 1) ? "," : "");
        }
        fprintf(fp, "        ],\n");

        // RF Init Calib Config
        fprintf(fp, "        \"rlRfInitCalConf_t\": {\n");
        fprintf(fp, "          \"calibEnMask\": \"0x1FF0\"\n");
        fprintf(fp, "        },\n");

        // Frame Config
        fprintf(fp, "        \"rlFrameCfg_t\": {\n");
        fprintf(fp, "          \"chirpEndIdx\": %d,\n", config.frameCfg.chirpEndIdx);
        fprintf(fp, "          \"chirpStartIdx\": %d,\n", config.frameCfg.chirpStartIdx);
        fprintf(fp, "          \"numLoops\": %d,\n", config.frameCfg.numLoops);
        fprintf(fp, "          \"numFrames\": %d,\n", config.frameCfg.numFrames);
        fprintf(fp, "          \"framePeriodicity_msec\": %.1f,\n", framePeriodicity_msec);
        fprintf(fp, "          \"triggerSelect\": %d,\n", devId == 0 ? 1 : 2); // SW trigger for master, HW for slaves
        fprintf(fp, "          \"frameTriggerDelay\": 0.0\n");
        fprintf(fp, "        },\n");

        // Empty arrays
        fprintf(fp, "        \"rlBpmChirps\": [],\n");
        
        // Misc Config
        fprintf(fp, "        \"rlRfMiscConf_t\": {\n");
        fprintf(fp, "          \"miscCtl\": \"%d\"\n", config.miscCfg.miscCtl);
        fprintf(fp, "        },\n");

        fprintf(fp, "        \"rlRfPhaseShiftCfgs\": [],\n");
        fprintf(fp, "        \"rlRfProgFiltConfs\": [],\n");

        // Test Source (empty template)
        fprintf(fp, "        \"rlTestSource_t\": {\n");
        fprintf(fp, "          \"rlTestSourceObjects\": [\n");
        fprintf(fp, "            {\n");
        fprintf(fp, "              \"rlTestSourceObject_t\": {\n");
        fprintf(fp, "                \"posX_m\": %.1f,\n", 4.0 + devId * 3.0);
        fprintf(fp, "                \"posY_m\": %.1f,\n", 3.0 + devId * 2.0);
        fprintf(fp, "                \"posZ_m\": 0.0,\n");
        fprintf(fp, "                \"velX_m_sec\": 0.0,\n");
        fprintf(fp, "                \"velY_m_sec\": 0.0,\n");
        fprintf(fp, "                \"velZ_m_sec\": 0.0,\n");
        fprintf(fp, "                \"sigLvl_dBFS\": -2.5,\n");
        fprintf(fp, "                \"posXMin_m\": -327.0,\n");
        fprintf(fp, "                \"posYMin_m\": 0.0,\n");
        fprintf(fp, "                \"posZMin_m\": -327.0,\n");
        fprintf(fp, "                \"posXMax_m\": 327.0,\n");
        fprintf(fp, "                \"posYMax_m\": 327.0,\n");
        fprintf(fp, "                \"posZMax_m\": 327.0\n");
        fprintf(fp, "              }\n");
        fprintf(fp, "            },\n");
        fprintf(fp, "            {\n");
        fprintf(fp, "              \"rlTestSourceObject_t\": {\n");
        fprintf(fp, "                \"posX_m\": 327.0,\n");
        fprintf(fp, "                \"posY_m\": 327.0,\n");
        fprintf(fp, "                \"posZ_m\": 0.0,\n");
        fprintf(fp, "                \"velX_m_sec\": 0.0,\n");
        fprintf(fp, "                \"velY_m_sec\": 0.0,\n");
        fprintf(fp, "                \"velZ_m_sec\": 0.0,\n");
        fprintf(fp, "                \"sigLvl_dBFS\": -95.0,\n");
        fprintf(fp, "                \"posXMin_m\": -327.0,\n");
        fprintf(fp, "                \"posYMin_m\": 0.0,\n");
        fprintf(fp, "                \"posZMin_m\": -327.0,\n");
        fprintf(fp, "                \"posXMax_m\": 327.0,\n");
        fprintf(fp, "                \"posYMax_m\": 327.0,\n");
        fprintf(fp, "                \"posZMax_m\": 327.0\n");
        fprintf(fp, "              }\n");
        fprintf(fp, "            }\n");
        fprintf(fp, "          ],\n");
        fprintf(fp, "          \"rlTestSourceRxAntPos\": [\n");
        for (int rx = 0; rx < 4; rx++) {
            fprintf(fp, "            {\n");
            fprintf(fp, "              \"rlTestSourceAntPos_t\": {\n");
            fprintf(fp, "                \"antPosX\": %.1f,\n", rx * 0.5);
            fprintf(fp, "                \"antPosZ\": 0.0\n");
            fprintf(fp, "              }\n");
            fprintf(fp, "            }%s\n", (rx < 3) ? "," : "");
        }
        fprintf(fp, "          ],\n");
        fprintf(fp, "          \"rlTestSourceTxAntPos\": [\n");
        for (int tx = 0; tx < 3; tx++) {
            fprintf(fp, "            {\n");
            fprintf(fp, "              \"rlTestSourceAntPos_t\": {\n");
            fprintf(fp, "                \"antPosX\": 0.0,\n");
            fprintf(fp, "                \"antPosZ\": 0.0\n");
            fprintf(fp, "              }\n");
            fprintf(fp, "            }%s\n", (tx < 2) ? "," : "");
        }
        fprintf(fp, "          ],\n");
        fprintf(fp, "          \"miscFunCtrl\": 0\n");
        fprintf(fp, "        },\n");

        // LDO Bypass Config
        fprintf(fp, "        \"rlRfLdoBypassCfg_t\": {\n");
        fprintf(fp, "          \"ldoBypassEnable\": %d,\n", config.ldoCfg.ldoBypassEnable);
        fprintf(fp, "          \"supplyMonIrDrop\": %d,\n", config.ldoCfg.supplyMonIrDrop);
        fprintf(fp, "          \"ioSupplyIndicator\": %d\n", config.ldoCfg.ioSupplyIndicator);
        fprintf(fp, "        },\n");

        fprintf(fp, "        \"rlLoopbackBursts\": [],\n");
        fprintf(fp, "        \"rlDynChirpCfgs\": [],\n");
        fprintf(fp, "        \"rlDynPerChirpPhShftCfgs\": []\n");
        fprintf(fp, "      },\n");

        // Raw Data Capture Config
        fprintf(fp, "      \"rawDataCaptureConfig\": {\n");
        fprintf(fp, "        \"rlDevDataFmtCfg_t\": {\n");
        fprintf(fp, "          \"iqSwapSel\": %d,\n", config.dataFmtCfg.iqSwapSel);
        fprintf(fp, "          \"chInterleave\": %d\n", config.dataFmtCfg.chInterleave);
        fprintf(fp, "        },\n");
        fprintf(fp, "        \"rlDevDataPathCfg_t\": {\n");
        fprintf(fp, "          \"intfSel\": %d,\n", config.datapathCfg.intfSel);
        fprintf(fp, "          \"transferFmtPkt0\": \"0x%X\",\n", config.datapathCfg.transferFmtPkt0);
        fprintf(fp, "          \"transferFmtPkt1\": \"0x%X\",\n", config.datapathCfg.transferFmtPkt1);
        fprintf(fp, "          \"cqConfig\": 0,\n");
        fprintf(fp, "          \"cq0TransSize\": 0,\n");
        fprintf(fp, "          \"cq1TransSize\": 0,\n");
        fprintf(fp, "          \"cq2TransSize\": 0\n");
        fprintf(fp, "        },\n");
        fprintf(fp, "        \"rlDevDataPathClkCfg_t\": {\n");
        fprintf(fp, "          \"laneClkCfg\": %d,\n", config.datapathClkCfg.laneClkCfg);
        fprintf(fp, "          \"dataRate_Mbps\": %d\n", config.datapathClkCfg.dataRate == 1 ? 600 : 450);
        fprintf(fp, "        },\n");
        fprintf(fp, "        \"rlDevCsi2Cfg_t\": {\n");
        fprintf(fp, "          \"lanePosPolSel\": \"0x%X\",\n", config.csi2LaneCfg.lanePosPolSel);
        fprintf(fp, "          \"lineStartEndDis\": %d\n", config.csi2LaneCfg.lineStartEndDis);
        fprintf(fp, "        }\n");
        fprintf(fp, "      },\n");
        fprintf(fp, "      \"monitoringConfig\": {\n");
        fprintf(fp, "      }\n");
        fprintf(fp, "    }%s\n", (devId < num_devices - 1) ? "," : "");
    }

    fprintf(fp, "  ],\n");

    // Processing Chain Config
    fprintf(fp, "  \"processingChainConfig\": {\n");
    fprintf(fp, "    \"detectionChain\": {\n");
    fprintf(fp, "      \"name\": \"TI_GenericChain\",\n");
    fprintf(fp, "      \"detectionLoss\": 1,\n");
    fprintf(fp, "      \"systemLoss\": 1,\n");
    fprintf(fp, "      \"implementationMargin\": 2,\n");
    fprintf(fp, "      \"detectionSNR\": 12,\n");
    fprintf(fp, "      \"theoreticalRxAntennaGain\": 9,\n");
    fprintf(fp, "      \"theoreticalTxAntennaGain\": 9\n");
    fprintf(fp, "    }\n");
    fprintf(fp, "  }\n");

    fprintf(fp, "}\n");

    fclose(fp);
    printf("Successfully exported configuration to %s\n", filename);
    return 0;
}


/**
 * @brief Application entry point
 * 
 * @param argc 
 * @param argv 
 * @return int 
 */
int main (int argc, char *argv[]) {
  DEBUG_PRINT("MMWave EVM configuration and control application\n");
  unsigned char default_ip_addr[] = "192.168.33.180";
  unsigned int default_port = 5001U;
  unsigned char capture_path[128];
  strcpy(capture_path, "/mnt/ssd/");  // Root capture path
  unsigned char default_capture_directory[64];
  sprintf(default_capture_directory, "%s_%lu", "MMWL_Capture", (unsigned long int)time(NULL));
  int status = 0;
  float default_recording_duration = 1.0;   // min

  parser_t parser = init_parser(
    PROG_NAME,
    "Configuration and control tool for TI MMWave cascade Evaluation Module"
  );
  g_parser = &parser;

  atexit(cleanup);  // Call the cleanup function before exiting the program
  signal(SIGINT, signal_handler);  // Catch CTRL+C to enable memory deallocation

  option_t opt_capturedir = {
    .args = "-d",
    .argl = "--capture-dir",
    .help = "Name of the director where to store recordings on the DSP board",
    .type = OPT_STR,
    .default_value = default_capture_directory
  };
  add_arg(&parser, &opt_capturedir);

  option_t opt_port = {
    .args = "-p",
    .argl = "--port",
    .help = "Port number the DSP board server app is listening on",
    .type = OPT_INT,
    .default_value = &default_port,
  };
  add_arg(&parser, &opt_port);

  option_t opt_ipaddr = {
    .args = "-i",
    .argl = "--ip-addr",
    .help = "IP Address of the MMWCAS DSP evaluation module",
    .type = OPT_STR,
    .default_value = default_ip_addr,
  };
  add_arg(&parser, &opt_ipaddr);

  option_t opt_config = {
    .args = "-c",
    .argl = "--configure",
    .help = "Configure the MMWCAS-RF-EVM board",
    .type = OPT_BOOL,
  };
  add_arg(&parser, &opt_config);

  option_t opt_record = {
    .args = "-r",
    .argl = "--record",
    .help = "Trigger data recording. This assumes that configuration is completed.",
    .type = OPT_BOOL,
  };
  add_arg(&parser, &opt_record);

  option_t opt_record_duration = {
    .args = "-t",
    .argl = "--time",
    .help = "Indicate how long the recording should last in minutes. Default: 1 min",
    .type = OPT_FLOAT,
    .default_value = &default_recording_duration,
  };
  add_arg(&parser, &opt_record_duration);

  option_t opt_config_file = {
    .args = "-f",
    .argl = "--cfg",
    .help = "TOML Configuration file. Overwrite the default config when provided",
    .type = OPT_STR,
    .default_value = NULL,
  };
  add_arg(&parser, &opt_config_file);

  option_t opt_help = {
    .args = "-h",
    .argl = "--help",
    .help = "Print CLI option help and exit.",
    .type = OPT_BOOL,
    .default_value = NULL,
    .callback = help,
  };
  add_arg(&parser, &opt_help);

  option_t opt_version = {
    .args = "-v",
    .argl = "--version",
    .help = "Print program version and exit.",
    .type = OPT_BOOL,
    .callback = print_version,
  };
  add_arg(&parser, &opt_version);

  // Parse command line for continuous mode
    option_t opt_continuous = {
        .args = "-m",
        .argl = "--monitor",
        .help = "Enable continuous monitoring mode",
        .type = OPT_BOOL,
    };
    add_arg(&parser, &opt_continuous);
    
    option_t opt_interval = {
        .args = "-n",
        .argl = "--interval",
        .help = "Monitoring interval in seconds (default: 10)",
        .type = OPT_INT,
        .default_value = &((int){10}),
    };
    add_arg(&parser, &opt_interval);
    
    parse(&parser, argc, argv);

  // Print help
  if ((unsigned char*)get_option(&parser, "help") != NULL) {
    print_help(&parser);
    exit(0);
  }

  unsigned char *monitor_mode = (unsigned char*)get_option(&parser, "monitor");
  int monitor_interval = *(int*)get_option(&parser, "interval");

  unsigned char *ip_addr = (unsigned char*)get_option(&parser, "ip-addr");
  unsigned int port = *(unsigned int*)get_option(&parser, "port");
  // Store IP address in global variable for logging
  strncpy(g_ip_addr, ip_addr, sizeof(g_ip_addr) - 1);
  g_ip_addr[sizeof(g_ip_addr) - 1] = '\0';
  unsigned char *capture_directory = (unsigned char*)get_option(&parser, "capture-dir");
  sprintf(capture_path, "/mnt/ssd/");
  // Construct JSON filename with same name as capture directory
  char json_filename[256];
  sprintf(json_filename, "%s.mmwave.json", capture_directory);
  /* Record CLI option possible values are:
   *  - start: To start a recording and exit
   *  - stop: Stop a recording and exit
   *  - oneshot: Start a recording, wait for it's complemention and stop it.
   */
  unsigned char *record = (unsigned char*)get_option(&parser, "record");
  float record_duration = *(float*)get_option(&parser, "time");
  record_duration *= 60 * 1000;  // convert into milliseconds

  unsigned char *config_filename = (unsigned char*)get_option(&parser, "cfg");

  // Configuration
  devConfig_t config;

  /*  Device map:  master | slave 1  | slave 2  | slave 3 */
  config.deviceMap =  1   | (1 << 1) | (1 << 2) | (1 << 3);
  MMWL_AssignDeviceMap(config.deviceMap, &config.masterMap, &config.slavesMap);

  config.frameCfg = frameCfgArgs;
  config.profileCfg = profileCfgArgs;
  config.chirpCfg = chirpCfgArgs;
  config.adcOutCfg = adcOutCfgArgs;
  config.dataFmtCfg = dataFmtCfgArgs;
  config.channelCfg = channelCfgArgs;
  config.csi2LaneCfg = csi2LaneCfgArgs;
  config.datapathCfg = datapathCfgArgs;
  config.datapathClkCfg = datapathClkCfgArgs;
  config.hsClkCfg = hsClkCfgArgs;
  config.ldoCfg = ldoCfgArgs;
  config.lpmCfg = lpmCfgArgs;
  config.miscCfg = miscCfgArgs;

  if (config_filename != NULL) {
    // Read parameters from config file
    read_config(config_filename, &config);
  }

  /**
   * @note: The adcOutCfg is used to overwrite the dataFmtCfg
   *
   * In a unified config file, it'll make for sense to have a single
   * source of truth for the ADC data format. And therefore use the
   * same data for setting both.
   */
  config.dataFmtCfg.rxChannelEn = channelCfgArgs.rxChannelEn;
  config.dataFmtCfg.adcBits = adcOutCfgArgs.fmt.b2AdcBits;
  config.dataFmtCfg.adcFmt = adcOutCfgArgs.fmt.b2AdcOutFmt;

  // config to ARM the TDA
  rlTdaArmCfg_t tdaCfg = {
    .captureDirectory = capture_path,
    .framePeriodicity = (frameCfgArgs.framePeriodicity * 5)/(1000*1000),
    .numberOfFilesToAllocate = 0,
    .numberOfFramesToCapture = 0, // config.frameCfg.numFrames,
    .dataPacking = 0, // 0: 16-bit | 1: 12-bit
  };

  if ((unsigned char *)get_option(&parser, "configure") != NULL) {
    // Connect to TDA
    status = MMWL_TDAInit(ip_addr, port, config.deviceMap);
    check(status,
      "[MMWCAS-DSP] TDA Connected!",
      "[MMWCAS-DSP] Couldn't connect to TDA board!\n", 32, TRUE);

    // Start configuration
    configure(config);
    // Export to JSON
    export_config_to_json(config, json_filename, 4);
    msleep(2000);
  }

  if ((unsigned char *)get_option(&parser, "record") != NULL) {
    // CONTINUOUS MONITORING LOOP
        if (monitor_mode != NULL) {
            printf("[MONITOR] Starting continuous monitoring mode\n");
            printf("[MONITOR] Interval: %d seconds\n", monitor_interval);
            
            int capture_count = 0;
            
            while (1) { // Infinite loop - use Ctrl+C to stop
                capture_count++;
                time_t now = time(NULL);
                
                // Generate unique capture directory
                char capture_dir[128];
                sprintf(capture_dir, "MMWL_Capture_%lu", (unsigned long)now);
                
                // Update capture path
                char full_capture_path[256];
                sprintf(full_capture_path, "%s%s", capture_path, capture_dir);
                tdaCfg.captureDirectory = full_capture_path;
                
                printf("\n[MONITOR #%d] Starting capture: %s\n", 
                       capture_count, capture_dir);
                
                // Arm TDA
                status = MMWL_ArmingTDA(tdaCfg);
                check(status, 
                      "[MMWCAS-DSP] Arming TDA",
                      "[MMWCAS-DSP] TDA Arming failed!", 32, FALSE);
                
                if (status != 0) {
                    printf("[MONITOR] Warning: TDA arming failed, retrying...\n");
                    msleep(2000);
                    continue;
                }
                
                msleep(2000);
                
                // Start framing
                for (int i = 3; i >= 0; i--) {
                    status += MMWL_StartFrame(1U << i);
                }
                check(status,
                      "[MMWCAS-RF] Framing ...",
                      "[MMWCAS-RF] Failed to initiate framing!", 
                      config.deviceMap, FALSE);
                
                // Wait for capture duration
                msleep((unsigned long int)monitor_interval * 1000);
                
                // Stop framing
                for (int i = 3; i >= 0; i--) {
                    status += MMWL_StopFrame(1U << i);
                }
                
                status += MMWL_DeArmingTDA();
                check(status,
                      "[MMWCAS-RF] Stop recording",
                      "[MMWCAS-RF] Failed to de-arm TDA board!", 32, FALSE);
                
                printf("[MONITOR #%d] Capture complete\n", capture_count);
                
                // Export JSON configuration
                char json_filename[256];
                sprintf(json_filename, "%s.mmwave.json", capture_dir);
                export_config_to_json(config, json_filename, 4);
                
                // Start async transfer (non-blocking)
                start_async_transfer(capture_dir, capture_count);
                printf("[MONITOR #%d] Transfer started in background\n", 
                       capture_count);
                
                // Small delay before next capture to ensure clean state
                msleep(1000);
                
                printf("[MONITOR] Ready for next capture...\n");
            }
        } else {
          // Construct the full capture path for single-run mode
          char full_capture_path_single[256];
          sprintf(full_capture_path_single, "%s%s", capture_path, capture_directory);
          tdaCfg.captureDirectory = full_capture_path_single;

	  // Arm TDA
          status = MMWL_ArmingTDA(tdaCfg);
          check(status,
            "[MMWCAS-DSP] Arming TDA",
            "[MMWCAS-DSP] TDA Arming failed!\n", 32, TRUE);

          msleep(2000);

          // Start framing
          for (int i = 3; i >=0; i--) {
            status += MMWL_StartFrame(1U << i);
          }
          check(status,
            "[MMWCAS-RF] Framing ...",
            "[MMWCAS-RF] Failed to initiate framing!\n", config.deviceMap, TRUE);

          msleep((unsigned long int)record_duration);

          // Stop framing
          for (int i = 3; i >= 0; i--) {
            status += MMWL_StopFrame(1U << i);
          }

          status += MMWL_DeArmingTDA();
          check(status,
            "[MMWCAS-RF] Stop recording",
            "[MMWCAS-RF] Failed to de-arm TDA board!\n", 32, TRUE);
          msleep(1000);
          // Export JSON configuration to match monitor mode behavior
          char json_filename_single[256];
          sprintf(json_filename_single, "%s.mmwave.json", capture_directory);
          export_config_to_json(config, json_filename_single, 4);

          // Start async transfer (non-blocking)
          printf("[SINGLE-RUN] Starting background SCP transfer...\n");
          start_async_transfer((const char*)capture_directory, 1);
        }
  }
  return 0;
}
