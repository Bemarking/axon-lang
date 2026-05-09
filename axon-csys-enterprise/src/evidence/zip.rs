//! § Fase 27.f — Pure-Rust byte-deterministic ZIP encoder + reader.
//!
//! Produces standard ZIP archives (PKZIP APPNOTE.TXT v6.3.x compatible)
//! that are bit-identical across regenerations and across host
//! platforms. The encoder is STORE-only (no DEFLATE) — the
//! compression-jitter risk that plagues `zip` crate / `python zipfile`
//! comes from zlib version drift; we sidestep it by not compressing.
//!
//! Determinism guarantees:
//!
//!   - All file mtimes fixed to `1980-01-01 00:00:00 UTC` (DOS epoch
//!     floor — the lowest legal ZIP timestamp).
//!   - Filenames emitted in the order supplied by the caller (the
//!     evidence builder sorts before passing in).
//!   - Local file header (LFH), central directory header (CDFH), and
//!     end-of-central-directory (EOCD) records use canonical fixed
//!     fields; no version-of-the-tool or hostname leakage.
//!   - File names encoded UTF-8 with the EFS bit (general purpose
//!     bit 11) set so cross-platform extractors interpret them
//!     consistently.
//!   - External file attributes set to `0644 << 16` (canonical Unix
//!     0644 read-write owner, read group/other) so chmod inferred at
//!     extraction is consistent.
//!
//! The reader is intentionally minimal: walks the central directory,
//! validates magic + signatures, returns `(name, content)` pairs in
//! the order they appear in the central directory. Adopters who want
//! richer extraction (preserve mtime, etc.) should use a full-featured
//! ZIP library — this reader is for verification, not general use.

use super::EvidenceError;

const LFH_SIGNATURE: u32 = 0x04034b50;
const CDFH_SIGNATURE: u32 = 0x02014b50;
const EOCD_SIGNATURE: u32 = 0x06054b50;

const VERSION_NEEDED_TO_EXTRACT: u16 = 20;
const VERSION_MADE_BY: u16 = 20; // host = MS-DOS (0), version = 20.

// General Purpose Bit Flag bits used:
//   bit 11 (0x0800) — Language encoding flag (EFS); filename is UTF-8.
const GP_FLAG_UTF8: u16 = 0x0800;

const COMPRESSION_STORE: u16 = 0;

const FIXED_DOS_DATE: u16 = 0x0021; // 1980-01-01
const FIXED_DOS_TIME: u16 = 0x0000; // 00:00:00

// External file attribute = 0o100644 << 16 (Unix regular file, 0644).
// Stored in the high 16 bits of `external_file_attributes`. The low
// 16 bits are the MS-DOS file attribute byte; we set 0 (no archive
// flag, etc.) for full determinism.
const EXTERNAL_FILE_ATTRIBUTES: u32 = 0o100_0644 << 16;

// ──────────────────────────────────────────────────────────────────────
// CRC-32/IEEE table (polynomial 0xEDB88320). Reflected, standard
// CRC-32 used by ZIP, gzip, PNG, etc.
// ──────────────────────────────────────────────────────────────────────

static CRC32_TABLE: [u32; 256] = build_crc32_table();

const fn build_crc32_table() -> [u32; 256] {
    let mut table = [0u32; 256];
    let mut i = 0;
    while i < 256 {
        let mut c = i as u32;
        let mut j = 0;
        while j < 8 {
            c = if c & 1 == 1 {
                0xEDB88320 ^ (c >> 1)
            } else {
                c >> 1
            };
            j += 1;
        }
        table[i] = c;
        i += 1;
    }
    table
}

fn crc32(data: &[u8]) -> u32 {
    let mut c = 0xFFFFFFFFu32;
    for &b in data {
        c = CRC32_TABLE[((c ^ b as u32) & 0xFF) as usize] ^ (c >> 8);
    }
    c ^ 0xFFFFFFFF
}

// ──────────────────────────────────────────────────────────────────────
// Encoder
// ──────────────────────────────────────────────────────────────────────

/// Write the supplied (name, content) pairs as a standard ZIP archive.
/// Files are emitted in the order supplied — caller is responsible
/// for sort-determinism. Returns the archive bytes.
pub fn write_archive(files: &[(String, Vec<u8>)]) -> Result<Vec<u8>, EvidenceError> {
    // Pre-size the output buffer to a reasonable estimate. Underestimates
    // are fine; over-allocating is the only perf concern.
    let est = files
        .iter()
        .map(|(n, c)| n.len() + c.len() + 80)
        .sum::<usize>()
        + 22;
    let mut out = Vec::with_capacity(est);

    let mut central_dir = Vec::with_capacity(files.len() * 64);
    let mut entries_written = 0u16;

    for (name, content) in files {
        let name_bytes = name.as_bytes();
        if name_bytes.len() > u16::MAX as usize {
            return Err(EvidenceError::InvalidPath(name.clone()));
        }
        if content.len() > u32::MAX as usize {
            return Err(EvidenceError::FileTooLarge(
                name.clone(),
                content.len() as u64,
            ));
        }
        let crc = crc32(content);
        let size = content.len() as u32;
        let lfh_offset = out.len() as u32;

        // Local file header
        out.extend_from_slice(&LFH_SIGNATURE.to_le_bytes());
        out.extend_from_slice(&VERSION_NEEDED_TO_EXTRACT.to_le_bytes());
        out.extend_from_slice(&GP_FLAG_UTF8.to_le_bytes());
        out.extend_from_slice(&COMPRESSION_STORE.to_le_bytes());
        out.extend_from_slice(&FIXED_DOS_TIME.to_le_bytes());
        out.extend_from_slice(&FIXED_DOS_DATE.to_le_bytes());
        out.extend_from_slice(&crc.to_le_bytes());
        out.extend_from_slice(&size.to_le_bytes()); // compressed size
        out.extend_from_slice(&size.to_le_bytes()); // uncompressed size
        out.extend_from_slice(&(name_bytes.len() as u16).to_le_bytes());
        out.extend_from_slice(&0u16.to_le_bytes()); // extra field length
        out.extend_from_slice(name_bytes);
        // No extra field, no data descriptor.
        out.extend_from_slice(content);

        // Central directory file header
        central_dir.extend_from_slice(&CDFH_SIGNATURE.to_le_bytes());
        central_dir.extend_from_slice(&VERSION_MADE_BY.to_le_bytes());
        central_dir.extend_from_slice(&VERSION_NEEDED_TO_EXTRACT.to_le_bytes());
        central_dir.extend_from_slice(&GP_FLAG_UTF8.to_le_bytes());
        central_dir.extend_from_slice(&COMPRESSION_STORE.to_le_bytes());
        central_dir.extend_from_slice(&FIXED_DOS_TIME.to_le_bytes());
        central_dir.extend_from_slice(&FIXED_DOS_DATE.to_le_bytes());
        central_dir.extend_from_slice(&crc.to_le_bytes());
        central_dir.extend_from_slice(&size.to_le_bytes()); // compressed size
        central_dir.extend_from_slice(&size.to_le_bytes()); // uncompressed size
        central_dir.extend_from_slice(&(name_bytes.len() as u16).to_le_bytes());
        central_dir.extend_from_slice(&0u16.to_le_bytes()); // extra field length
        central_dir.extend_from_slice(&0u16.to_le_bytes()); // file comment length
        central_dir.extend_from_slice(&0u16.to_le_bytes()); // disk number start
        central_dir.extend_from_slice(&0u16.to_le_bytes()); // internal file attrs
        central_dir.extend_from_slice(&EXTERNAL_FILE_ATTRIBUTES.to_le_bytes());
        central_dir.extend_from_slice(&lfh_offset.to_le_bytes());
        central_dir.extend_from_slice(name_bytes);

        entries_written += 1;
    }

    let cd_offset = out.len() as u32;
    let cd_size = central_dir.len() as u32;
    out.extend_from_slice(&central_dir);

    // End-of-central-directory record
    out.extend_from_slice(&EOCD_SIGNATURE.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes()); // number of this disk
    out.extend_from_slice(&0u16.to_le_bytes()); // disk where CD starts
    out.extend_from_slice(&entries_written.to_le_bytes()); // CD records on this disk
    out.extend_from_slice(&entries_written.to_le_bytes()); // total CD records
    out.extend_from_slice(&cd_size.to_le_bytes());
    out.extend_from_slice(&cd_offset.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes()); // ZIP file comment length

    Ok(out)
}

// ──────────────────────────────────────────────────────────────────────
// Reader
// ──────────────────────────────────────────────────────────────────────

/// Read the supplied ZIP bytes. Returns `(name, content)` pairs in
/// central-directory order. Validates magic + sizes + per-file CRC.
pub fn read_archive(bytes: &[u8]) -> Result<Vec<(String, Vec<u8>)>, EvidenceError> {
    let eocd_offset = find_eocd(bytes)?;
    if eocd_offset + 22 > bytes.len() {
        return Err(EvidenceError::ZipParseError("EOCD truncated".into()));
    }
    let eocd = &bytes[eocd_offset..];
    let total_entries = u16::from_le_bytes([eocd[10], eocd[11]]);
    let cd_size = u32::from_le_bytes([eocd[12], eocd[13], eocd[14], eocd[15]]);
    let cd_offset = u32::from_le_bytes([eocd[16], eocd[17], eocd[18], eocd[19]]) as usize;

    if cd_offset + cd_size as usize > eocd_offset {
        return Err(EvidenceError::ZipParseError("CD overlaps EOCD".into()));
    }

    let mut out: Vec<(String, Vec<u8>)> = Vec::with_capacity(total_entries as usize);
    let mut p = cd_offset;
    for _ in 0..total_entries {
        if p + 46 > bytes.len() {
            return Err(EvidenceError::ZipParseError("CD truncated".into()));
        }
        let sig = u32::from_le_bytes([bytes[p], bytes[p + 1], bytes[p + 2], bytes[p + 3]]);
        if sig != CDFH_SIGNATURE {
            return Err(EvidenceError::ZipParseError(format!(
                "bad CDFH signature {sig:#010x}"
            )));
        }
        let compression = u16::from_le_bytes([bytes[p + 10], bytes[p + 11]]);
        if compression != COMPRESSION_STORE {
            return Err(EvidenceError::ZipParseError(format!(
                "compression {compression} unsupported (STORE-only)"
            )));
        }
        let crc = u32::from_le_bytes([bytes[p + 16], bytes[p + 17], bytes[p + 18], bytes[p + 19]]);
        let comp_size =
            u32::from_le_bytes([bytes[p + 20], bytes[p + 21], bytes[p + 22], bytes[p + 23]]);
        let uncomp_size =
            u32::from_le_bytes([bytes[p + 24], bytes[p + 25], bytes[p + 26], bytes[p + 27]]);
        if comp_size != uncomp_size {
            return Err(EvidenceError::ZipParseError(format!(
                "comp_size {comp_size} != uncomp_size {uncomp_size} (STORE-only)"
            )));
        }
        let name_len = u16::from_le_bytes([bytes[p + 28], bytes[p + 29]]) as usize;
        let extra_len = u16::from_le_bytes([bytes[p + 30], bytes[p + 31]]) as usize;
        let comment_len = u16::from_le_bytes([bytes[p + 32], bytes[p + 33]]) as usize;
        let lfh_offset =
            u32::from_le_bytes([bytes[p + 42], bytes[p + 43], bytes[p + 44], bytes[p + 45]])
                as usize;
        let name_start = p + 46;
        let name_end = name_start + name_len;
        if name_end > bytes.len() {
            return Err(EvidenceError::ZipParseError("CD name truncated".into()));
        }
        let name = std::str::from_utf8(&bytes[name_start..name_end])
            .map_err(|e| EvidenceError::ZipParseError(format!("filename UTF-8: {e}")))?
            .to_owned();

        // Locate + decode the LFH so we can read the file content.
        if lfh_offset + 30 > bytes.len() {
            return Err(EvidenceError::ZipParseError("LFH truncated".into()));
        }
        let lfh = &bytes[lfh_offset..];
        let lfh_sig = u32::from_le_bytes([lfh[0], lfh[1], lfh[2], lfh[3]]);
        if lfh_sig != LFH_SIGNATURE {
            return Err(EvidenceError::ZipParseError(format!(
                "bad LFH signature {lfh_sig:#010x}"
            )));
        }
        let lfh_name_len = u16::from_le_bytes([lfh[26], lfh[27]]) as usize;
        let lfh_extra_len = u16::from_le_bytes([lfh[28], lfh[29]]) as usize;
        let content_start = lfh_offset + 30 + lfh_name_len + lfh_extra_len;
        let content_end = content_start + comp_size as usize;
        if content_end > bytes.len() {
            return Err(EvidenceError::ZipParseError("content truncated".into()));
        }
        let content = bytes[content_start..content_end].to_vec();

        // Verify CRC.
        let actual_crc = crc32(&content);
        if actual_crc != crc {
            return Err(EvidenceError::ZipParseError(format!(
                "CRC mismatch on {name:?}: stored {crc:#010x} actual {actual_crc:#010x}"
            )));
        }

        out.push((name, content));
        p = name_end + extra_len + comment_len;
    }

    Ok(out)
}

fn find_eocd(bytes: &[u8]) -> Result<usize, EvidenceError> {
    // EOCD is at the end. The minimum EOCD size is 22 bytes; it can
    // be followed by up to 65535 bytes of ZIP file comment. Scan
    // backwards for the signature.
    if bytes.len() < 22 {
        return Err(EvidenceError::ZipParseError("file < 22 bytes".into()));
    }
    let max_back = (bytes.len() - 22).min(0xFFFF + 22);
    for off in (0..=max_back).rev() {
        let pos = bytes.len() - 22 - off;
        let sig = u32::from_le_bytes([bytes[pos], bytes[pos + 1], bytes[pos + 2], bytes[pos + 3]]);
        if sig == EOCD_SIGNATURE {
            return Ok(pos);
        }
    }
    Err(EvidenceError::ZipParseError(
        "EOCD signature not found".into(),
    ))
}
