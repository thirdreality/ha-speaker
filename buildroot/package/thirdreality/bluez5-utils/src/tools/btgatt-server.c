/*
 *  BlueZ - Bluetooth protocol stack for Linux
 *
 *  Copyright (C) 2014  Google Inc.
 *
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 */

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#include <string.h>
#include <ctype.h>
#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <time.h>
#include <stdlib.h>
#include <getopt.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <pthread.h>
#include <signal.h>
#include <sys/wait.h>
#include <sys/select.h>
#include <sys/signal.h>
#include <sys/types.h>
#include <cjson/cJSON.h>

#include "lib/bluetooth.h"
#include "lib/hci.h"
#include "lib/hci_lib.h"
#include "lib/l2cap.h"
#include "lib/uuid.h"
#include "monitor/bt.h"

#include "src/shared/mainloop.h"
#include "src/shared/util.h"
#include "src/shared/att.h"
#include "src/shared/hci.h"
#include "src/shared/queue.h"
#include "src/shared/timeout.h"
#include "src/shared/gatt-db.h"
#include "src/shared/gatt-server.h"

#ifdef __linux__
#include <net/if.h>
#endif

static void str2uuid(const char *str, uint8_t *value, uint8_t type);
static struct server *server_create(int fd);

static void start_advertising(void);
static void stop_advertising(void);
static void reset_no_client_timeout(void);
static void no_client_timeout_cb(int timeout_id, void *user_data);
static const char* get_device_name(void);

// Keep the original 128-bit definitions for fallback
#define SERVICE_UUID_STR "6e400000-0000-4e98-8024-bc5b71e0893e"
#define WIFI_CONFIG_CHAR_UUID_STR "6e400001-0000-4e98-8024-bc5b71e0893e"
#define ATT_CID 4

static struct hci_dev_info hdi;
static int ctl;
static struct server *server;
static bool wifi_config_completed = false;

// Timeout settings (15 minutes = 900 seconds)
#define NO_CLIENT_TIMEOUT_SECONDS 900

struct server {
	int fd;
	struct bt_att *att;
	struct gatt_db *db;
	struct bt_gatt_server *gatt;

	// WiFi configuration characteristic
	struct gatt_db_attribute *wifi_chara_att;
	uint16_t wifi_chara_handle;

	bool notifying;
	bool notification_ready;
	pthread_mutex_t notification_lock;

    // BLE GATT long write buffer for WiFi config
#define MAX_WRITE_BUFFER 1024
    char write_buffer[MAX_WRITE_BUFFER];
    size_t write_buffer_len;
    bool write_in_progress;
};

// Global state management variables
static bool client_connected = false;
static bool advertising = false;
static volatile bool should_exit = false;
static unsigned int no_client_timeout_id = 0;

static void delayed_exit_cb(int timeout_id, void *user_data)
{
    printf("[EXIT] Delayed exit after sending WiFi result\n");
    should_exit = true;
    mainloop_quit();
}

static int process_wifi_config(const char *json_str, char *response, size_t response_len)
{
    cJSON *root = cJSON_Parse(json_str);
    if (!root) {
        printf("[DEBUG] Failed to parse JSON\n");
        snprintf(response, response_len, "{\"err\":\"bad fmt\"}");
        return -1;
    }
    cJSON *ssid_item = cJSON_GetObjectItem(root, "ssid");
    if (!ssid_item || !cJSON_IsString(ssid_item)) {
        printf("[DEBUG] Missing or invalid SSID\n");
        cJSON_Delete(root);
        snprintf(response, response_len, "{\"err\":\"bad ssid\"}");
        return -1;
    }

    char *ssid = ssid_item->valuestring;
    cJSON *password_item = cJSON_GetObjectItem(root, "pw");
    char *password = NULL;
    if (password_item && cJSON_IsString(password_item)) {
        password = password_item->valuestring;
    }

    char cmd[512];
    snprintf(cmd, sizeof(cmd),
             "/usr/share/thirdreality/script/wifi_connect connect '%s' '%s'",
             ssid, password);
    
    int exit_status = system(cmd);
    int exit_code = WEXITSTATUS(exit_status);

    printf("[WIFI] wifi_connect exit code: %d\n", exit_code);
    if (exit_code != 0) {
        printf("[WIFI] WiFi connection failed with exit code: %d\n", exit_code);

        const char *err_msg;
        switch (exit_code) {
            case 10:
                err_msg = "SSID not found";
                break;
            case 12:
                err_msg = "Failed to get IP";
                break;
            case 13:
                err_msg = "Connect failed";
                break;
            case 14:
                err_msg = "Switch WiFi failed";
                break;
            default:
                err_msg = "Unknown error";
                break;
        }

        snprintf(response, response_len, "{\"err\":\"%s\"}", err_msg);
        cJSON_Delete(root);
        return -1;
    }

    FILE *device_info_fp = fopen("/data/conf/device.json", "r");
    if (!device_info_fp) {
        printf("[WIFI] Failed to open device.json\n");
        snprintf(response, response_len, "{\"err\":\"Failed to read IP\"}");
        cJSON_Delete(root);
        return -1;
    }

    fseek(device_info_fp, 0, SEEK_END);
    long file_size = ftell(device_info_fp);
    fseek(device_info_fp, 0, SEEK_SET);

    char *device_info_content = malloc(file_size + 1);
    if (!device_info_content) {
        printf("[WIFI] Failed to allocate memory for device.json\n");
        fclose(device_info_fp);
        snprintf(response, response_len, "{\"err\":\"Memory error\"}");
        cJSON_Delete(root);
        return -1;
    }

    fread(device_info_content, 1, file_size, device_info_fp);
    device_info_content[file_size] = '\0';
    fclose(device_info_fp);

    cJSON *device_info = cJSON_Parse(device_info_content);
    free(device_info_content);

    if (!device_info) {
        printf("[WIFI] Failed to parse device.json\n");
        snprintf(response, response_len, "{\"err\":\"Invalid device_info\"}");
        cJSON_Delete(root);
        return -1;
    }

    cJSON *network = cJSON_GetObjectItem(device_info, "network");
    cJSON *ip_item = network ? cJSON_GetObjectItem(network, "ip") : NULL;

    if (!ip_item || !cJSON_IsString(ip_item)) {
        printf("[WIFI] Failed to get IP from device.json\n");
        snprintf(response, response_len, "{\"err\":\"IP not found\"}");
        cJSON_Delete(device_info);
        cJSON_Delete(root);
        return -1;
    }

    char *ip = ip_item->valuestring;
    if (!ip || strlen(ip) == 0) {
        printf("[WIFI] IP address is empty in device.json\n");
        snprintf(response, response_len, "{\"err\":\"IP is empty\"}");
        cJSON_Delete(device_info);
        cJSON_Delete(root);
        return -1;
    }

    printf("[WIFI] WiFi connection successful! IP: %s\n", ip);

    snprintf(response, response_len, "{\"ip\":\"%s\"}", ip);

    cJSON_Delete(device_info);
    cJSON_Delete(root);
    return 0;
}

static void att_disconnect_cb(int err, void *user_data)
{
    struct server *server = user_data;
    printf("ATT Disconnect callback: err=%d (%s)\n", err, strerror(err));

    printf("[DISCONNECT] Client disconnected\n");

    client_connected = false;

    if (err == 8) {
        printf("[DISCONNECT] LINK_SUPERVISION_TIMEOUT detected - connection lost due to timeout\n");
    }

    if (wifi_config_completed) {
        printf("[EXIT] WiFi configuration completed and client disconnected, exiting...\n");
        should_exit = true;
        mainloop_quit();
        return;
    }

    mainloop_quit();
}

static void send_notification(struct server *server, const char *message, uint16_t char_handle)
{
    if (!server->gatt) {
        printf("[DEBUG] No GATT server available for notification\n");
        return;
    }

    size_t message_len = strlen(message);
    if (message_len <= 20) {
        uint8_t buffer[21];
        memcpy(buffer, message, message_len);
        bool result = bt_gatt_server_send_notification(server->gatt, char_handle,
                buffer, message_len, false);
        printf("[DEBUG] Single packet notification result: %s\n", result ? "SUCCESS" : "FAILED");
        return;
    }

    size_t total_len = message_len + 1;

    uint16_t current_mtu = bt_gatt_server_get_mtu(server->gatt);
    size_t max_payload = current_mtu - 3;

    if (total_len <= max_payload) {
        uint8_t *buffer = malloc(total_len);
        if (!buffer) {
            printf("[DEBUG] Failed to allocate buffer for notification\n");
            return;
        }

        memcpy(buffer, message, message_len);
        buffer[message_len] = '\n';

        bool result = bt_gatt_server_send_notification(server->gatt, char_handle,
                buffer, total_len, false);

        free(buffer);
        return;
    }

    printf("[DEBUG] Message too long (%zu bytes with newline), fragmenting into %zu-byte chunks\n", 
           total_len, max_payload);

    size_t offset = 0;
    int fragment_num = 0;

    while (offset < total_len) {
        size_t remaining = total_len - offset;
        size_t chunk_size = (remaining > max_payload) ? max_payload : remaining;

        uint8_t *buffer = malloc(chunk_size);
        if (!buffer) {
            printf("[DEBUG] Failed to allocate buffer for fragment %d\n", fragment_num);
            break;
        }

        if (offset < message_len) {
            size_t data_to_copy = (chunk_size <= (message_len - offset)) ? chunk_size : (message_len - offset);
            memcpy(buffer, message + offset, data_to_copy);

            if (offset + data_to_copy >= message_len) {
                buffer[data_to_copy] = '\n';
            }
        } else {
            buffer[0] = '\n';
        }

        bool result = bt_gatt_server_send_notification(server->gatt, char_handle,
                buffer, chunk_size, false);

        free(buffer);

        if (!result) {
            printf("[DEBUG] Fragment %d failed to send\n", fragment_num);
            break;
        }

        printf("[DEBUG] Fragment %d sent successfully\n", fragment_num);

        offset += chunk_size;
        fragment_num++;

        if (offset < total_len) {
            usleep(50000); // 50ms delay for MTU=23 to ensure stable delivery
        }
    }

    printf("[DEBUG] Fragmentation complete: sent %d fragments, total %zu bytes\n", 
           fragment_num, offset);
}

static void wifi_config_write_cb(struct gatt_db_attribute *attrib,
                unsigned int id, uint16_t offset,
                const uint8_t *value, size_t len,
                uint8_t opcode, struct bt_att *att,
                void *user_data)
{
    struct server *server = user_data;
    char *json_str = NULL;
    char response[256];

    gatt_db_attribute_write_result(attrib, id, 0);

    if (opcode == BT_ATT_OP_PREP_WRITE_REQ) {
        if (len > 0) {
            memcpy(server->write_buffer + offset, value, len);
            if (offset + len > server->write_buffer_len)
                server->write_buffer_len = offset + len;
        } else {
            printf("[DEBUG] Prepare Write: len=0, skip memcpy\n");
        }
        server->write_in_progress = true;
        return;
    } else if (opcode == BT_ATT_OP_EXEC_WRITE_REQ) {
        if (!server->write_in_progress || server->write_buffer_len == 0) {
            printf("[DEBUG] Execute Write but no data in buffer\n");
            snprintf(response, sizeof(response), "{\"ip\":\"\"}");
            goto send_response;
        }
        size_t actual_len = server->write_buffer_len;
        for (size_t i = 0; i < server->write_buffer_len; i++) {
            if (server->write_buffer[i] == '\n') {
                actual_len = i;
                break;
            }
        }
        json_str = malloc(actual_len + 1);
        if (!json_str) {
            snprintf(response, sizeof(response), "{\"ip\":\"\"}");
            server->write_buffer_len = 0;
            server->write_in_progress = false;
            goto send_response;
        }
        memcpy(json_str, server->write_buffer, actual_len);
        json_str[actual_len] = '\0';
        server->write_buffer_len = 0;
        server->write_in_progress = false;
        if (!client_connected) {
            snprintf(response, sizeof(response), "{\"err\":\"BLE lost\"}");
            free(json_str);
            goto send_response;
        }
        process_wifi_config(json_str, response, sizeof(response));
        free(json_str);
        goto send_response;
    } else if (opcode == BT_ATT_OP_WRITE_REQ) {
        if (offset > 0) {
            snprintf(response, sizeof(response), "{\"ip\":\"\"}");
            goto send_response;
        }
        if (len == 0) {
            snprintf(response, sizeof(response), "{\"ip\":\"\"}");
            goto send_response;
        }
        size_t actual_len = len;
        for (size_t i = 0; i < len; i++) {
            if (value[i] == '\n') {
                actual_len = i;
                break;
            }
        }
        json_str = malloc(actual_len + 1);
        if (!json_str) {
            snprintf(response, sizeof(response), "{\"ip\":\"\"}");
            goto send_response;
        }
        memcpy(json_str, value, actual_len);
        json_str[actual_len] = '\0';
        if (!client_connected) {
            snprintf(response, sizeof(response), "{\"err\":\"BLE lost\"}");
            free(json_str);
            goto send_response;
        }
        process_wifi_config(json_str, response, sizeof(response));
        free(json_str);
        goto send_response;
    } else if (opcode == BT_ATT_OP_WRITE_CMD) {
        if (offset > 0) {
            return;
        }
        if (len == 0) {
            return;
        }
        if (server->write_buffer_len + len > MAX_WRITE_BUFFER) {
            server->write_buffer_len = 0;
            return;
        }
        memcpy(server->write_buffer + server->write_buffer_len, value, len);
        server->write_buffer_len += len;
        size_t json_end = 0;
        bool found_newline = false;
        for (size_t i = 0; i < server->write_buffer_len; i++) {
            if (server->write_buffer[i] == '\n') {
                json_end = i;
                found_newline = true;
                break;
            }
        }
        if (!found_newline) {
            return;
        }
        char *json_str = malloc(json_end + 1);
        if (!json_str) {
            server->write_buffer_len = 0;
            return;
        }
        memcpy(json_str, server->write_buffer, json_end);
        json_str[json_end] = '\0';
        server->write_buffer_len = 0;
        if (!client_connected) {
            free(json_str);
            return;
        }
        process_wifi_config(json_str, response, sizeof(response));
        free(json_str);
        pthread_mutex_lock(&server->notification_lock);
        if (server->notifying && client_connected) {
            printf("[DEBUG] Sending WiFi result notification: %s\n", response);
            send_notification(server, response, server->wifi_chara_handle);
            
            wifi_config_completed = true;
            mainloop_add_timeout(2000, delayed_exit_cb, NULL, NULL);
        } else {
            printf("[DEBUG] Client not subscribed to notifications or disconnected, cannot send result\n");
        }
        pthread_mutex_unlock(&server->notification_lock);
        return;
    }

send_response:
        if (!client_connected) {
            return;
        }
        usleep(100000);
        if (!client_connected) {
            return;
        }
        pthread_mutex_lock(&server->notification_lock);
        if (server->notifying && client_connected) {
            printf("[DEBUG] Sending WiFi result notification: %s\n", response);
            send_notification(server, response, server->wifi_chara_handle);
            
            wifi_config_completed = true;
            mainloop_add_timeout(2000, delayed_exit_cb, NULL, NULL);
        } else {
            printf("[DEBUG] Client not subscribed to notifications or disconnected, cannot send result\n");
        }
        pthread_mutex_unlock(&server->notification_lock);
}

static void str2uuid(const char *str, uint8_t *value, uint8_t type)
{
    if (strlen(str) != 36) {
        return;
    }

    int i = 0, j = 0;
    char buf[3] = {0};

    while (i < 36 && j < 16) {
        if (str[i] == '-') {
            i++;
            continue;
        }
        buf[0] = str[i++];
        buf[1] = str[i++];
        value[j++] = (uint8_t)strtoul(buf, NULL, 16);
    }
}

static void cccd_read_cb(struct gatt_db_attribute *attrib,
				unsigned int id, uint16_t offset,
				uint8_t opcode, struct bt_att *att,
				void *user_data)
{
	struct server *server = user_data;
	uint8_t value[2] = {0, 0};

	if (server->notifying) {
		value[0] = 0x01;
	}

	gatt_db_attribute_read_result(attrib, id, 0, value, 2);
}

static void cccd_write_cb(struct gatt_db_attribute *attrib,
				unsigned int id, uint16_t offset,
				const uint8_t *value, size_t len,
				uint8_t opcode, struct bt_att *att,
				void *user_data)
{
	struct server *server = user_data;

	if (len != 2) {
		gatt_db_attribute_write_result(attrib, id, BT_ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LEN);
		return;
	}

	uint16_t cccd_value = (value[1] << 8) | value[0];

	pthread_mutex_lock(&server->notification_lock);

	if (cccd_value & 0x01) {
		server->notifying = true;
		server->notification_ready = true;
	} else if (cccd_value & 0x02) {
		server->notifying = true;
		server->notification_ready = true;
	} else {
		server->notifying = false;
		server->notification_ready = false;
	}

	pthread_mutex_unlock(&server->notification_lock);
	gatt_db_attribute_write_result(attrib, id, 0);
}

static void gap_device_name_read_cb(struct gatt_db_attribute *attrib,
                unsigned int id, uint16_t offset,
                uint8_t opcode, struct bt_att *att,
                void *user_data)
{
    const char *name = get_device_name();
    uint16_t len = strlen(name);

    if (offset > len) {
        gatt_db_attribute_read_result(attrib, id, BT_ATT_ERROR_INVALID_OFFSET, NULL, 0);
        return;
    }

    len -= offset;
    gatt_db_attribute_read_result(attrib, id, 0, (uint8_t *)(name + offset), len);
}

static void gap_appearance_read_cb(struct gatt_db_attribute *attrib,
                unsigned int id, uint16_t offset,
                uint8_t opcode, struct bt_att *att,
                void *user_data)
{
    uint8_t appearance[2] = { 0x00, 0x00 }; // Unknown appearance

    if (offset > 2) {
        gatt_db_attribute_read_result(attrib, id, BT_ATT_ERROR_INVALID_OFFSET, NULL, 0);
        return;
    }

    gatt_db_attribute_read_result(attrib, id, 0, appearance + offset, 2 - offset);
}

static void populate_gap_service(struct server *server)
{
    struct gatt_db_attribute *service;
    bt_uuid_t uuid;

    bt_uuid16_create(&uuid, 0x1800);
    service = gatt_db_add_service(server->db, &uuid, true, 6);

    bt_uuid16_create(&uuid, 0x2A00);
    gatt_db_service_add_characteristic(service, &uuid,
            BT_ATT_PERM_READ,
            BT_GATT_CHRC_PROP_READ,
            gap_device_name_read_cb, NULL, server);

    bt_uuid16_create(&uuid, 0x2A01);
    gatt_db_service_add_characteristic(service, &uuid,
            BT_ATT_PERM_READ,
            BT_GATT_CHRC_PROP_READ,
            gap_appearance_read_cb, NULL, server);

    gatt_db_service_set_active(service, true);
    printf("[DEBUG] GAP service populated\n");
}

static void populate_gatt_service(struct server *server)
{
    struct gatt_db_attribute *service, *characteristic;
    bt_uuid_t uuid;

    bt_uuid16_create(&uuid, 0x1801);
    service = gatt_db_add_service(server->db, &uuid, true, 6);

    bt_uuid16_create(&uuid, 0x2A05);
    characteristic = gatt_db_service_add_characteristic(service, &uuid,
            BT_ATT_PERM_READ,
            BT_GATT_CHRC_PROP_INDICATE,
            NULL, NULL, server);

    bt_uuid16_create(&uuid, 0x2902);
    gatt_db_service_add_descriptor(characteristic, &uuid,
            BT_ATT_PERM_READ | BT_ATT_PERM_WRITE,
            cccd_read_cb, cccd_write_cb, server);

    gatt_db_service_set_active(service, true);
}

static void populate_wifi_service(struct server *server)
{
    struct gatt_db_attribute *service, *characteristic;
    bt_uuid_t uuid;
    uint128_t uuid_value;

    gatt_db_ccc_register(server->db, cccd_read_cb, cccd_write_cb, NULL, server);

    str2uuid(SERVICE_UUID_STR, (uint8_t *)&uuid_value, 16);
    bt_uuid128_create(&uuid, uuid_value);

    service = gatt_db_add_service(server->db, &uuid, true, 16);
    if (!service) {
        printf("[ERROR] Failed to create WiFi service!\n");
        return;
    }

    str2uuid(WIFI_CONFIG_CHAR_UUID_STR, (uint8_t *)&uuid_value, 16);
    bt_uuid128_create(&uuid, uuid_value);

    characteristic = gatt_db_service_add_characteristic(service, &uuid,
            BT_ATT_PERM_WRITE,
            BT_GATT_CHRC_PROP_WRITE | BT_GATT_CHRC_PROP_WRITE_WITHOUT_RESP | BT_GATT_CHRC_PROP_NOTIFY,
            NULL, wifi_config_write_cb, server);

    if (!characteristic) {
        printf("[ERROR] Failed to create WiFi characteristic!\n");
        return;
    }

    if (!gatt_db_service_add_ccc(characteristic, BT_ATT_PERM_READ | BT_ATT_PERM_WRITE)) {
        printf("[ERROR] Failed to add WiFi CCCD descriptor!\n");
        return;
    }

    server->wifi_chara_att = characteristic;
    server->wifi_chara_handle = gatt_db_attribute_get_handle(characteristic);

    if (!gatt_db_service_set_active(service, true)) {
        printf("[ERROR] Failed to activate WiFi service!\n");
        return;
    }
}

static struct server *server_create(int fd)
{
	struct server *server;

    server = malloc(sizeof(*server));
	if (!server) {
        printf("[DEBUG] Failed to allocate server\n");
		return NULL;
	}

    memset(server, 0, sizeof(*server));
    server->fd = fd;

	server->att = bt_att_new(fd, false);
	if (!server->att) {
        printf("[DEBUG] Failed to create ATT\n");
        free(server);
        return NULL;
	}

	if (!bt_att_set_close_on_unref(server->att, true)) {
        printf("[DEBUG] Failed to set close on unref\n");
        bt_att_unref(server->att);
        free(server);
        return NULL;
    }

    bt_att_register_disconnect(server->att, att_disconnect_cb, server, NULL);

	server->db = gatt_db_new();
	if (!server->db) {
        printf("[DEBUG] Failed to create GATT DB\n");
        bt_att_unref(server->att);
        free(server);
        return NULL;
	}

	server->gatt = bt_gatt_server_new(server->db, server->att, 23, 0);
	if (!server->gatt) {
        printf("[DEBUG] Failed to create GATT server\n");
        gatt_db_unref(server->db);
        bt_att_unref(server->att);
        free(server);
        return NULL;
	}

    server->notifying = false;
    server->notification_ready = false;
    pthread_mutex_init(&server->notification_lock, NULL);

    populate_gap_service(server);
    populate_gatt_service(server);

    populate_wifi_service(server);
    return server;
}

static void server_destroy(struct server *server)
{
	bt_gatt_server_unref(server->gatt);
	gatt_db_unref(server->db);
}

static int l2cap_le_att_listen_and_accept(bdaddr_t *src, int sec,
		uint8_t src_type)
{
	int sk, nsk;
	struct sockaddr_l2 srcaddr, addr;
	socklen_t optlen;
	struct bt_security btsec;
	char ba[18];

	sk = socket(PF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP);
	if (sk < 0) {
		perror("Failed to create L2CAP socket");
		return -1;
	}

	memset(&srcaddr, 0, sizeof(srcaddr));
	srcaddr.l2_family = AF_BLUETOOTH;
	srcaddr.l2_cid = htobs(ATT_CID);
	srcaddr.l2_bdaddr_type = src_type;
	bacpy(&srcaddr.l2_bdaddr, src);
	if (bind(sk, (struct sockaddr *) &srcaddr, sizeof(srcaddr)) < 0) {
		perror("Failed to bind L2CAP socket");
		goto fail;
	}

	memset(&btsec, 0, sizeof(btsec));
	btsec.level = sec;
	if (setsockopt(sk, SOL_BLUETOOTH, BT_SECURITY, &btsec,
				sizeof(btsec)) != 0) {
		fprintf(stderr, "Failed to set L2CAP security level\n");
		goto fail;
	}

	if (listen(sk, 10) < 0) {
		perror("Listening on socket failed");
		goto fail;
	}

	fd_set readfds;
	int max_fd = sk;
	int select_count = 0;
	time_t start_time = time(NULL);

	sigset_t empty_mask;
	sigemptyset(&empty_mask);

	while (!should_exit) {
		FD_ZERO(&readfds);
		FD_SET(sk, &readfds);

		struct timespec timeout;
		timeout.tv_sec = 1;
		timeout.tv_nsec = 0;

		int ret = pselect(max_fd + 1, &readfds, NULL, NULL, &timeout, &empty_mask);
		select_count++;

		time_t current_time = time(NULL);
		if (current_time - start_time >= NO_CLIENT_TIMEOUT_SECONDS) {
			should_exit = true;
			goto fail;
		}

		if (ret < 0) {
			if (errno == EINTR) {
				continue;
			}
			perror("Select failed");
			goto fail;
		} else if (ret == 0) {
			if (should_exit) {
				printf("[SELECT] should_exit detected during timeout, breaking\n");
				break;
			}
			continue;
		} else if (FD_ISSET(sk, &readfds)) {
			printf("[SELECT] Socket ready for accept (count: %d)\n", select_count);
			break;
		}
	}

	if (should_exit) {
		printf("Exiting before accepting connection\n");
		goto fail;
	}

	memset(&addr, 0, sizeof(addr));
	optlen = sizeof(addr);
	nsk = accept(sk, (struct sockaddr *) &addr, &optlen);
	if (nsk < 0) {
		perror("Accept failed");
		goto fail;
	}

	ba2str(&addr.l2_bdaddr, ba);
	printf("Connect from %s\n", ba);
	close(sk);

	return nsk;

fail:
	close(sk);
	return -1;
}

static void signal_handler(int signum)
{
    const char msg[] = "\n[SIGNAL] Signal received, setting should_exit = true\n";
    write(STDOUT_FILENO, msg, sizeof(msg) - 1);

    switch (signum) {
    case SIGINT:
        {
            const char sigint_msg[] = "[SIGNAL] SIGINT (Ctrl+C) received!\n";
            write(STDOUT_FILENO, sigint_msg, sizeof(sigint_msg) - 1);
            should_exit = true;
            mainloop_quit();
            break;
        }
    case SIGTERM:
        {
            const char sigterm_msg[] = "[SIGNAL] SIGTERM received!\n";
            write(STDOUT_FILENO, sigterm_msg, sizeof(sigterm_msg) - 1);

            if (advertising) {
                const char adv_msg[] = "[SIGNAL] Stopping advertising due to SIGTERM\n";
                write(STDOUT_FILENO, adv_msg, sizeof(adv_msg) - 1);

                struct bt_hci_cmd_le_set_adv_enable param;
                param.enable = 0;

                int hdev = hci_get_route(NULL);
                if (hdev >= 0) {
                    int dd = hci_open_dev(hdev);
                    if (dd >= 0) {
                        struct hci_request rq;
                        uint8_t status;
                        memset(&rq, 0, sizeof(rq));
                        rq.ogf = OGF_LE_CTL;
                        rq.ocf = BT_HCI_CMD_LE_SET_ADV_ENABLE;
                        rq.cparam = &param;
                        rq.clen = sizeof(param);
                        rq.rparam = &status;
                        rq.rlen = 1;
                        hci_send_req(dd, &rq, 1000);
                        hci_close_dev(dd);
                    }
                }
                advertising = false;
            }

            should_exit = true;
            mainloop_quit();
            break;
        }
    default:
        break;
    }
}

static void signal_cb(int signum, void *user_data)
{
    switch (signum) {
    case SIGINT:
    case SIGTERM:
        printf("\n  [SIGNAL] Received termination signal (%d)\n", signum);
        should_exit = true;
        mainloop_quit();
        break;
    default:
        break;
    }
}

static void send_cmd(int cmd, void *params, int params_len)
{
	struct hci_request rq;
	uint8_t status;
	int dd, hdev;

	hdev = hci_get_route(NULL);
	if (hdev < 0) {
		perror("Could not get HCI device");
		exit(1);
	}

	dd = hci_open_dev(hdev);
	if (dd < 0) {
		perror("Could not open device");
		exit(1);
	}

	memset(&rq, 0, sizeof(rq));
	rq.ogf = OGF_LE_CTL;
	rq.ocf = cmd;
	rq.cparam = params;
	rq.clen = params_len;
	rq.rparam = &status;
	rq.rlen = 1;

    hci_send_req(dd, &rq, 1000);
    hci_close_dev(dd);
}

static char device_name_cache[32] = {0};
static bool device_name_initialized = false;

static const char* get_device_name(void)
{
    if (device_name_initialized) {
        return device_name_cache;
    }

    FILE* fp = fopen("/data/conf/device.json", "r");
    if (fp) {
        fseek(fp, 0, SEEK_END);
        long file_size = ftell(fp);
        fseek(fp, 0, SEEK_SET);
        
        if (file_size > 0 && file_size < 1024 * 1024) {
            char *content = malloc(file_size + 1);
            if (content) {
                size_t read_size = fread(content, 1, file_size, fp);
                content[read_size] = '\0';

                cJSON *root = cJSON_Parse(content);
                free(content);

                if (root) {
                    cJSON *device = cJSON_GetObjectItem(root, "device");
                    cJSON *name_item = device ? cJSON_GetObjectItem(device, "name") : NULL;

                    if (name_item && cJSON_IsString(name_item)) {
                        char *name_str = name_item->valuestring;
                        size_t name_len = strlen(name_str);
                        if (name_len > 0 && name_len < sizeof(device_name_cache)) {
                            strncpy(device_name_cache, name_str, sizeof(device_name_cache) - 1);
                            device_name_cache[sizeof(device_name_cache) - 1] = '\0';
                            printf("[DEBUG] device name: %s\n", device_name_cache);
                            cJSON_Delete(root);
                            fclose(fp);
                            device_name_initialized = true;
                            return device_name_cache;
                        }
                    }
                    cJSON_Delete(root);
                }
            }
        }
        fclose(fp);
    }

    printf("[DEVICE_NAME] Failed to read from device.json, using fallback\n");
    time_t now = time(NULL);
    snprintf(device_name_cache, sizeof(device_name_cache), 
            "3RSPK-%04lX", (unsigned long)(now & 0xFFFF));
    printf("[DEVICE_NAME] Generated from timestamp: %s\n", device_name_cache);

    device_name_initialized = true;
    return device_name_cache;
}

static void set_adv_parameters(void)
{
	struct bt_hci_cmd_le_set_adv_parameters param;

    param.own_addr_type = 0x00;    /* Use public address */
    // Use much longer intervals for maximum stability against timeouts
	param.min_interval = cpu_to_le16(0x0100);  // 160ms for maximum stability
	param.max_interval = cpu_to_le16(0x0200);  // 320ms for very slow but stable advertising
    param.type = 0x00;        /* connectable no-direct advertising */
	param.direct_addr_type = 0x00;
	memset(param.direct_addr, 0, 6);
	param.channel_map = 0x07;
	param.filter_policy = 0x00;

	send_cmd(BT_HCI_CMD_LE_SET_ADV_PARAMETERS, (void *)&param, sizeof(param));
}

static void set_adv_enable(int enable)
{
    struct bt_hci_cmd_le_set_adv_enable param;
    if (enable !=0 && enable != 1) {
        printf("%s: invalid arg: %d\n", __func__, enable);
        return;
    }
    param.enable = enable;
    send_cmd(BT_HCI_CMD_LE_SET_ADV_ENABLE, (void *)&param, sizeof(param));
}

static void set_adv_response(void)
{
    struct bt_hci_cmd_le_set_scan_rsp_data param;
    const char *device_name = get_device_name();

    memset(&param, 0, sizeof(param));
    param.len = 0;

    size_t name_len = strlen(device_name);
    if (name_len > 29) {
        name_len = 29;
        printf("[ADV] Device name truncated to %zu characters\n", name_len);
    }

    param.data[param.len++] = name_len + 1;  // Length including type
    param.data[param.len++] = 0x09;          // Complete Local Name
    memcpy(&param.data[param.len], device_name, name_len);
    param.len += name_len;

    send_cmd(BT_HCI_CMD_LE_SET_SCAN_RSP_DATA, &param, sizeof(param));
}

static void set_adv_data(void)
{
    struct bt_hci_cmd_le_set_adv_data param;
    uint128_t uuid_value;

    memset(&param, 0, sizeof(param));
    param.len = 0;

    param.data[param.len++] = 2;
    param.data[param.len++] = 0x01;
    param.data[param.len++] = 0x04;  // LE General Discoverable Mode

    str2uuid(SERVICE_UUID_STR, (uint8_t *)&uuid_value, 16);
    param.data[param.len++] = 17;  // Length: 1 byte type + 16 bytes UUID
    param.data[param.len++] = 0x07;  // Complete List of 128-bit Service UUIDs
    for (int i = 0; i < 16; i++) {
        param.data[param.len + i] = ((uint8_t *)&uuid_value)[15 - i];
    }
    param.len += 16;

    // Add TX power
    param.data[param.len++] = 2;
    param.data[param.len++] = 0x0A;
    param.data[param.len++] = 0x00;

    send_cmd(BT_HCI_CMD_LE_SET_ADV_DATA, &param, sizeof(param));
}

void hci_dev_init(void)
{
	/* Open HCI socket	*/
	if ((ctl = socket(AF_BLUETOOTH, SOCK_RAW, BTPROTO_HCI)) < 0) {
		perror("Can't open HCI socket.");
		exit(1);
	}

	hdi.dev_id = 0;

	if (ioctl(ctl, HCIGETDEVINFO, (void *) &hdi)) {
		perror("Can't get device info");
		exit(1);
	}
}

// Advertising control functions
static void start_advertising(void)
{
    if (!advertising) {
        set_adv_enable(0);
        set_adv_data();
        set_adv_parameters();
        set_adv_response();
        set_adv_enable(1);

        advertising = true;
        printf("[ADV] Advertising restarted successfully\n");
    } else {
        printf("[ADV] Advertising already running\n");
    }
}

static void stop_advertising(void)
{
    if (advertising) {
        system("hcitool -i hci0 cmd 0x08 0x000A 01");

        printf("[ADV] Stopping advertising...\n");
        set_adv_enable(0);

        // Clear advertising data
        struct bt_hci_cmd_le_set_adv_data adv_clear;
        memset(&adv_clear, 0, sizeof(adv_clear));
        adv_clear.len = 0;
        send_cmd(BT_HCI_CMD_LE_SET_ADV_DATA, &adv_clear, sizeof(adv_clear));

        // Clear scan response data
        struct bt_hci_cmd_le_set_scan_rsp_data scan_clear;
        memset(&scan_clear, 0, sizeof(scan_clear));
        scan_clear.len = 0;
        send_cmd(BT_HCI_CMD_LE_SET_SCAN_RSP_DATA, &scan_clear, sizeof(scan_clear));

        advertising = false;
        printf("[ADV] Advertising stopped and data cleared\n");
    } else {
        printf("[ADV] Advertising already stopped\n");
    }
}

static void no_client_timeout_cb(int timeout_id, void *user_data)
{
    printf("[TIMEOUT] No client connected for %d seconds, exiting...\n", 
        NO_CLIENT_TIMEOUT_SECONDS);

    should_exit = true;
    mainloop_quit();
}

static void reset_no_client_timeout(void)
{
    if (no_client_timeout_id > 0) {
        mainloop_remove_timeout(no_client_timeout_id);
        no_client_timeout_id = 0;
    }

    if (!client_connected) {
        no_client_timeout_id = mainloop_add_timeout(NO_CLIENT_TIMEOUT_SECONDS * 1000,
                                                   no_client_timeout_cb, NULL, NULL);
        printf("[TIMEOUT] Started %d second timeout for no client connection\n", 
               NO_CLIENT_TIMEOUT_SECONDS);
    }
}

static void cleanup_on_exit(void)
{
    if (advertising) {
        printf("[CLEANUP] Cleaning up advertising on exit\n");

        struct bt_hci_cmd_le_set_adv_enable param;
        param.enable = 0;

        int hdev = hci_get_route(NULL);
        if (hdev >= 0) {
            int dd = hci_open_dev(hdev);
            if (dd >= 0) {
                struct hci_request rq;
                uint8_t status;
                memset(&rq, 0, sizeof(rq));
                rq.ogf = OGF_LE_CTL;
                rq.ocf = BT_HCI_CMD_LE_SET_ADV_ENABLE;
                rq.cparam = &param;
                rq.clen = sizeof(param);
                rq.rparam = &status;
                rq.rlen = 1;
                hci_send_req(dd, &rq, 1000);
                hci_close_dev(dd);
            }
        }
        advertising = false;
    }
}

int main(void)
{
	bdaddr_t src_addr;
	int fd;
	int sec = BT_SECURITY_LOW;
	uint8_t src_type = BDADDR_LE_PUBLIC;

	atexit(cleanup_on_exit);

	setvbuf(stdout, NULL, _IONBF, 0);
	setvbuf(stderr, NULL, _IONBF, 0);

	struct sigaction sa;
	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = signal_handler;
	sigemptyset(&sa.sa_mask);
	sa.sa_flags = 0;

	if (sigaction(SIGINT, &sa, NULL) == -1) {
		perror("sigaction SIGINT");
		return EXIT_FAILURE;
	}

	if (sigaction(SIGTERM, &sa, NULL) == -1) {
		perror("sigaction SIGTERM");
		return EXIT_FAILURE;
	}

	sigset_t blocked_signals;
	sigemptyset(&blocked_signals);
	sigaddset(&blocked_signals, SIGINT);
	sigaddset(&blocked_signals, SIGTERM);
	if (sigprocmask(SIG_BLOCK, &blocked_signals, NULL) == -1) {
		perror("sigprocmask");
		return EXIT_FAILURE;
	}

	hci_dev_init();

	while (!should_exit) {
		if (sigaction(SIGINT, &sa, NULL) == -1) {
			perror("sigaction SIGINT re-install");
		}
		if (sigaction(SIGTERM, &sa, NULL) == -1) {
			perror("sigaction SIGTERM re-install");
		}

		start_advertising();

		bacpy(&src_addr, BDADDR_ANY);
		fd = l2cap_le_att_listen_and_accept(&src_addr, sec, src_type);
		if (fd < 0) {
			fprintf(stderr, "Failed to accept L2CAP ATT connection\n");

			usleep(500000);
			return EXIT_FAILURE;
		}

		printf("[MAIN] Client connected! Creating GATT server...\n");

		stop_advertising();
		client_connected = true;

		mainloop_init();

		server = server_create(fd);
		if (!server) {
			close(fd);
			usleep(500000);
			return EXIT_FAILURE;
		}

		reset_no_client_timeout();

		mainloop_run_with_signal(signal_cb, NULL);
		
		if (should_exit) {
			printf("[MAIN] Exiting due to termination signal\n");
			break;
		}

		client_connected = false;
		advertising = false;

		if (no_client_timeout_id > 0) {
			mainloop_remove_timeout(no_client_timeout_id);
			no_client_timeout_id = 0;
		}

		sleep(1);
	}

	printf("\n\n[MAIN] Shutting down...\n");

	if (no_client_timeout_id > 0) {
		mainloop_remove_timeout(no_client_timeout_id);
	}

	stop_advertising();
	server_destroy(server);

	usleep(800000);
	return EXIT_SUCCESS;
}
