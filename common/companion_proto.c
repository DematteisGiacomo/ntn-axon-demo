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
#if defined(CONFIG_COMPANION_THUMB_BYTES)
BUILD_ASSERT(CONFIG_COMPANION_THUMB_W * CONFIG_COMPANION_THUMB_H ==
	     CONFIG_COMPANION_THUMB_BYTES);
#endif

static uint32_t frame_crc(const uint8_t *data, size_t len)
{
	return crc32_ieee(data, len);
}

int companion_frame_encode(const struct companion_detect_image *msg, uint8_t *wire, size_t wire_cap,
			   size_t *wire_len)
{
	const uint16_t image_len = msg->hdr.image_len;
	const size_t total = companion_wire_payload_len(image_len);

	if (image_len > COMPANION_MAX_IMAGE || total > wire_cap || wire_len == NULL) {
		return -EINVAL;
	}

	if (msg->hdr.magic != COMPANION_MAGIC || msg->hdr.version != COMPANION_VERSION ||
	    msg->hdr.msg_type != COMPANION_MSG_DETECT_IMAGE) {
		return -EINVAL;
	}

	memcpy(wire, &msg->hdr, COMPANION_HEADER_SIZE);
	memcpy(wire + COMPANION_HEADER_SIZE, msg->image, image_len);

	const uint32_t crc = frame_crc(wire, COMPANION_HEADER_SIZE + image_len);

	sys_put_le32(crc, wire + COMPANION_HEADER_SIZE + image_len);
	*wire_len = total;

	return 0;
}

int companion_header_from_wire(const uint8_t *wire, size_t avail, uint16_t *image_len_out)
{
	uint16_t image_len;

	if (wire == NULL || image_len_out == NULL || avail < COMPANION_HEADER_SIZE) {
		return -EINVAL;
	}

	if (sys_get_le32(wire) != COMPANION_MAGIC) {
		return -EINVAL;
	}
	if (wire[4] != COMPANION_VERSION || wire[5] != COMPANION_MSG_DETECT_IMAGE) {
		return -EINVAL;
	}

	image_len = sys_get_le16(wire + 13);
	if (image_len == 0U || image_len > COMPANION_MAX_IMAGE) {
		return -EINVAL;
	}

	*image_len_out = image_len;
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

	if (msg->hdr.magic != COMPANION_MAGIC || msg->hdr.version != COMPANION_VERSION ||
	    msg->hdr.msg_type != COMPANION_MSG_DETECT_IMAGE) {
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
