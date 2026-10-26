// Reading a picked video file in the browser, and keeping it around for
// the upload flow's review step.

/** Upload limits from the API: types it accepts (routes/clips.py), and clips are capped at 30s. */
export const ACCEPTED_TYPES = ['video/mp4', 'video/quicktime', 'video/webm'] as const;
export const MAX_DURATION_MS = 30_000;

/** The clip's length from its metadata, without decoding it. */
export function readVideoDuration(file: Blob): Promise<number> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.onloadedmetadata = () => {
      const ms = Math.round(video.duration * 1000);
      URL.revokeObjectURL(url);
      Number.isFinite(ms) && ms > 0 ? resolve(ms) : reject(new Error("Couldn't read the clip's length."));
    };
    video.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("That file doesn't look like a video we can read."));
    };
    video.src = url;
  });
}

// The file you uploaded, by clip id, for this browser session: the review
// step plays it (and jumps to each trick) before the processed version is
// on the CDN, and in mock mode, where there's no real video at all.
const previews = new Map<string, string>();

export function rememberPreview(clipId: string, file: Blob) {
  previews.set(clipId, URL.createObjectURL(file));
}

export function previewUrl(clipId: string): string | undefined {
  return previews.get(clipId);
}
