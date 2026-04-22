//! Subprocess-backed transformers (ffmpeg).

pub mod ffmpeg;

pub use self::ffmpeg::{FfmpegPipeline, FfmpegPool, FfmpegPoolConfig};
