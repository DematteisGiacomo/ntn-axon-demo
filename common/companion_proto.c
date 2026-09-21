/*
 * Copyright (c) 2026 Nordic Semiconductor ASA
 * SPDX-License-Identifier: LicenseRef-Nordic-5-Clause
 */

#include "companion_proto.h"

#include <errno.h>
#include <string.h>

#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/crc.h>
#include <zephyr/sys/util.h>

BUILD_ASSERT(sizeof(struct companion_header) == COMPANION_HEADER_SIZE);
BUILD_ASSERT(COMPANION_MAX_IMAGE <= COMPANION_IMAGE_ABS_MAX);

#if defined(CONFIG_COMPANION_CHUNKED_NTN)
BUILD_ASSERT(CONFIG_COMPANION_THUMB_FULL_W * CONFIG_COMPANION_THUMB_FULL_H ==
	     CONFIG_COMPANION_REASSEMBLY_BYTES);
BUILD_ASSERT(CONFIG_COMPANION_CHUNK_COUNT * CONFIG_COMPANION_CHUNK_BYTES ==
	     CONFIG_COMPANION_REASSEMBLY_BYTES);
#elif defined(CONFIG_COMPANION_THUMB_BYTES)
BUILD_ASSERT(CONFIG_COMPANION_THUMB_W * CONFIG_COMPANION_THUMB_H ==
	     CONFIG_COMPANION_THUMB_BYTES);
#endif

static uint32_t frame_crc(const uint8_t *data, size_t len)
{
	return crc32_ieee(data, len);
}

static int encode_wire(const struct companion_header *hdr, const uint8_t *image,
		       uint16_t image_len, uint8_t *wire, size_t wire_cap, size_t *wire_len)
{
	const size_t total = companion_wire_payload_len(image_len);

	if (image_len > COMPANION_MAX_IMAGE || total > wire_cap || wire_len == NULL) {
		return -EINVAL;
	}

	memcpy(wire, hdr, COMPANION_HEADER_SIZE);
	if (image_len > 0U && image != NULL) {
		memcpy(wire + COMPANION_HEADER_SIZE, image, image_len);
	}

	const uint32_t crc = frame_crc(wire, COMPANION_HEADER_SIZE + image_len);

	sys_put_le32(crc, wire + COMPANION_HEADER_SIZE + image_len);
	*wire_len = total;

	return 0;
}

int companion_frame_encode(const struct companion_detect_image *msg, uint8_t *wire, size_t wire_cap,
			   size_t *wire_len)
{
	const uint16_t image_len = msg->hdr.image_len;

	if (msg->hdr.magic != COMPANION_MAGIC || msg->hdr.version != COMPANION_VERSION ||
	    msg->hdr.msg_type != COMPANION_MSG_DETECT_IMAGE) {
		return -EINVAL;
	}

	return encode_wire(&msg->hdr, msg->image, image_len, wire, wire_cap, wire_len);
}

int companion_frame_encode_chunk(uint32_t frame_id, uint16_t top_score_mille, uint16_t full_w,
				 uint16_t full_h, uint8_t chunk_index, uint8_t chunk_total,
				 const uint8_t *chunk_data, uint16_t chunk_len, uint8_t *wire,
				 size_t wire_cap, size_t *wire_len)
{
	struct companion_header hdr = {
		.magic = COMPANION_MAGIC,
		.version = COMPANION_VERSION,
		.msg_type = COMPANION_MSG_DETECT_IMAGE_CHUNK,
		.frame_id = frame_id,
		.detect_count = chunk_index,
		.top_score_mille = top_score_mille,
		.image_len = chunk_len,
		.image_fmt = chunk_total,
		.thumb_w = full_w,
		.thumb_h = full_h,
	};

	if (chunk_index >= chunk_total || chunk_total == 0U || chunk_data == NULL) {
		return -EINVAL;
	}

	return encode_wire(&hdr, chunk_data, chunk_len, wire, wire_cap, wire_len);
}

int companion_header_from_wire(const uint8_t *wire, size_t avail, uint16_t *image_len_out,
			       uint8_t *msg_type_out)
{
	uint16_t image_len;
	uint8_t msg_type;

	if (wire == NULL || image_len_out == NULL || avail < COMPANION_HEADER_SIZE) {
		return -EINVAL;
	}

	if (sys_get_le32(wire) != COMPANION_MAGIC) {
		return -EINVAL;
	}
	if (wire[4] != COMPANION_VERSION) {
		return -EINVAL;
	}

	msg_type = wire[5];
	if (msg_type != COMPANION_MSG_DETECT_IMAGE &&
	    msg_type != COMPANION_MSG_DETECT_IMAGE_CHUNK) {
		return -EINVAL;
	}

	image_len = sys_get_le16(wire + 13);
	if (image_len == 0U || image_len > COMPANION_MAX_IMAGE) {
		return -EINVAL;
	}

	*image_len_out = image_len;
	if (msg_type_out != NULL) {
		*msg_type_out = msg_type;
	}

	return 0;
}

int companion_frame_decode(const uint8_t *wire, size_t wire_len, struct companion_detect_image *msg)
{
	uint16_t image_len;
	uint32_t expect_crc;
	uint32_t got_crc;

	if (wire_len < COMPANION_HEADER_SIZE + COMPANION_CRC_SIZE || msg == NULL) {
		return -EINVAL;
	}

	memcpy(&msg->hdr, wire, COMPANION_HEADER_SIZE);

	if (msg->hdr.magic != COMPANION_MAGIC || msg->hdr.version != COMPANION_VERSION) {
		return -EINVAL;
	}

	if (msg->hdr.msg_type != COMPANION_MSG_DETECT_IMAGE &&
	    msg->hdr.msg_type != COMPANION_MSG_DETECT_IMAGE_CHUNK) {
		return -EINVAL;
	}

	image_len = msg->hdr.image_len;
	if (image_len > COMPANION_MAX_IMAGE ||
	    wire_len != companion_wire_payload_len(image_len)) {
		return -EINVAL;
	}

	memcpy(msg->image, wire + COMPANION_HEADER_SIZE, image_len);

	expect_crc = frame_crc(wire, COMPANION_HEADER_SIZE + image_len);
	got_crc = sys_get_le32(wire + COMPANION_HEADER_SIZE + image_len);

	if (expect_crc != got_crc) {
		return -EBADMSG;
	}

	return 0;
}
