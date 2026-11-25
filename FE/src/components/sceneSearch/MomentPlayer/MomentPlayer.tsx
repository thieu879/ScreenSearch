import React, { useEffect, useRef, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { apiSrc, fetchMoment } from '../../../api/client';
import { boxAt, boxStyle, distanceAt, formatDistance, frameAt } from '../../../lib/momentOverlay';
import type { MomentDetail, MomentRef, MomentTrack } from '../../../types/api';
import './MomentPlayer.css';

interface MomentPlayerProps {
  moment: MomentRef;
}

/**
 * The redacted clip, with the vehicles the system tracked drawn on it.
 *
 * **The boxes are the point, and so is what the caption does not say.** Eight trajectory rules were
 * measured against a hand-labelled gold and none could tell a cut-in from an overtake on this
 * footage, so nothing here names a manoeuvre. What the geometry does support is the distance, and
 * that is what is shown: how close each vehicle came to the car, in metres, from the ground plane.
 *
 * **The `~` is not decoration.** The distance is `focal * typical_height / box_height`, so it assumes
 * a height for the class and inherits the declared FOV — and it measures to the camera, not to the
 * front of the car, which is a metre or two further forward.
 *
 * **Each box shows the distance on the frame being played**, not the track's minimum. The minimum
 * was on the tag first and it was wrong on screen in a way the number was not: an overtaking car
 * held its closest value long after it had gone, and two vehicles at obviously different depths read
 * the same. The minimum stays as the summary line, where it is true.
 *
 * `events`, where present, stay labelled as a human's reading. They are the one thing on this player
 * a person wrote rather than a measurement, and conflating the two is the whole failure this feature
 * was built to avoid.
 *
 * The overlay is driven by `requestAnimationFrame` rather than the video's `timeupdate` event, which
 * fires about four times a second — a quarter of the clip's 10 fps, so boxes would visibly lag the
 * vehicle they belong to. Tracks carry gaps where the detector missed a frame; nothing is drawn for
 * those rather than interpolating a box that was never measured.
 */
export const MomentPlayer: React.FC<MomentPlayerProps> = ({ moment }) => {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<MomentDetail | null>(null);
  const [frame, setFrame] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    let live = true;
    // A failed fetch costs the overlay, never the clip: the video is already playing from its own
    // URL and a missing annotation is not a reason to hide the footage.
    fetchMoment(moment.id)
      .then((data) => live && setDetail(data))
      .catch(() => live && setDetail(null));
    return () => {
      live = false;
    };
  }, [moment.id]);

  useEffect(() => {
    if (!detail) return undefined;
    let raf = 0;
    const tick = () => {
      const video = videoRef.current;
      if (video) setFrame(frameAt(video.currentTime, detail.fps));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [detail]);

  const nearest = moment.closest_m;

  return (
    <div className="moment-player">
      <p className="moment-player__label">{t('moment_label')}</p>

      <div className="moment-player__stage">
        <video
          ref={videoRef}
          className="moment-player__video"
          src={apiSrc(moment.video_url)}
          controls
          preload="metadata"
          playsInline
        />
        {detail?.tracks.map((track, index) => (
          <TrackBox key={`${track.label}-${index}`} track={track} frame={frame} />
        ))}
      </div>

      {nearest !== null && (
        <p className="moment-player__distance">
          {t('moment_closest')} <strong>{formatDistance(nearest)}</strong>
          <span className="moment-player__caveat">
            {' '}
            {/* `Trans` rather than `t`, because the two emphasised phrases are the load-bearing
                ones: *at that moment* separates this from the track minimum, and *camera* is what
                the metre figure is measured to. A caveat that loses its emphasis in one language
                and keeps it in the other is not the same caveat. */}
            <Trans i18nKey="moment_distance_caveat" components={{ em: <em /> }} />
          </span>
        </p>
      )}

      {moment.events.length > 0 && (
        <p className="moment-player__events">
          {t('moment_events', {
            events: moment.events
              .map(([start, end, label]) => `${label} ${start.toFixed(1)}–${end.toFixed(1)}s`)
              .join(', '),
          })}
        </p>
      )}
    </div>
  );
};

/** One tracked vehicle, drawn where it was on this frame — and nowhere at all when it was not seen. */
const TrackBox: React.FC<{ track: MomentTrack; frame: number }> = ({ track, frame }) => {
  const box = boxAt(track, frame);
  if (!box) return null;
  const now = distanceAt(track, frame);

  return (
    <div className="moment-player__box" style={boxStyle(box)}>
      <span className="moment-player__tag">
        {track.label}
        {now === null ? '' : ` ${formatDistance(now)}`}
      </span>
    </div>
  );
};
