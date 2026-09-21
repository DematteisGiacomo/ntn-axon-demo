/*
 * Copyright (c) 2026 Nordic Semiconductor ASA
 * SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
 *
 * UART + UDP framing for nRF54 person-detect thumbnail → nRF9151 → Iridium.
 */

#ifndef COMPANION_PROTO_H__
#define COMPANION_PROTO_H__

#include <stddef.h>
#include <stdint.h>

#define COMPANION_MAGIC          0x41584631U /* "AXF1" */
#define COMPANION_VERSION          1U
#define COMPANION_MSG_DETECT_IMAGE 1U

#define COMPANION_HEADER_SIZE      20U
#define COMPANION_CRC_SIZE         4U
/** Absolute protocol ceiling (legacy full thumb); Kconfig may use a smaller payload. */
#define COMPANION_IMAGE_ABS_MAX    2024U

#if defined(CONFIG_COMPANION_THUMB_BYTES)
#define COMPANION_MAX_IMAGE        CONFIG_COMPANION_THUMB_BYTES
#else
#define COMPANION_MAX_IMAGE        COMPANION_IMAGE_ABS_MAX
#endif

#define COMPANION_FRAME_MAX        (COMPANION_HEADER_SIZE + COMPANION_MAX_IMAGE + COMPANION_CRC_SIZE)
#define COMPANION_WIRE_MAX         COMPANION_FRAME_MAX

#define COMPANION_FMT_RAW_LUMA     0U
#define COMPANION_FMT_JPEG         1U

#define COMPANION_UART_ACK         0x06U

struct companion_header {
	uint32_t magic;
	uint8_t version;
	uint8_t msg_type;
	uint32_t frame_id;
	uint8_t detect_count;
	uint16_t top_score_mille;
	uint16_t image_len;
	uint8_t image_fmt;
	uint16_t thumb_w;
	uint16_t thumb_h;
} __packed;

struct companion_detect_image {
	struct companion_header hdr;
	uint8_t image[COMPANION_MAX_IMAGE];
};

/** Build wire frame (header + image + CRC32). Returns total length or negative errno. */
int companion_frame_encode(const struct companion_detect_image *msg, uint8_t *wire, size_t wire_cap,
			   size_t *wire_len);

/** Parse and validate wire frame into msg. Returns 0 or negative errno. */
int companion_frame_decode(const uint8_t *wire, size_t wire_len, struct companion_detect_image *msg);

/** Validate first COMPANION_HEADER_SIZE bytes; sets *image_len_out on success. */
int companion_header_from_wire(const uint8_t *wire, size_t avail, uint16_t *image_len_out);

static inline size_t companion_wire_payload_len(uint16_t image_len)
{
	return COMPANION_HEADER_SIZE + image_len + COMPANION_CRC_SIZE;
}

#endif /* COMPANION_PROTO_H__ */
