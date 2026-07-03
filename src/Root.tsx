import React from 'react';
import { Composition, useCurrentFrame, Img, staticFile, AbsoluteFill } from 'remotion';

// Generic BEIA reel: renders a vertical (1080x1920) reel from a list of card
// image URLs. Brand look (end-card name + accent colour) comes in as props so
// the one composition serves every brand — values supplied by beia_core from
// brand config at render time. Nothing here is brand-specific.

const CARD_DURATION = 150; // 5s @ 30fps
const FADE_DURATION = 20;

type ReelProps = {
  images: string[];
  brandName?: string;
  accentColor?: string;
};

const QuoteVideo: React.FC<ReelProps> = ({
  images,
  brandName = 'BEIA',
  accentColor = '#F97316',
}) => {
  const frame = useCurrentFrame();
  const totalFrames = images.length * CARD_DURATION;
  const currentCardIndex = Math.floor(frame / CARD_DURATION);
  const frameInCard = frame % CARD_DURATION;

  let opacity = 1;
  if (frameInCard < FADE_DURATION) {
    opacity = frameInCard / FADE_DURATION;
  } else if (frameInCard > CARD_DURATION - FADE_DURATION) {
    opacity = (CARD_DURATION - frameInCard) / FADE_DURATION;
  }

  const scale = 1 + (frameInCard / CARD_DURATION) * 0.02;
  const progress = frame / totalFrames;

  if (currentCardIndex >= images.length) {
    return (
      <AbsoluteFill style={{ backgroundColor: '#FFFFFF' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
          <p style={{ fontSize: 24, color: '#333' }}>{brandName}</p>
        </div>
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: '#FFFFFF' }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        opacity,
        transform: `scale(${scale})`,
      }}>
        <Img
          src={images[currentCardIndex].startsWith('http') ? images[currentCardIndex] : staticFile(images[currentCardIndex])}
          style={{ width: '100%', height: '100%', objectFit: 'contain' }}
        />
      </div>
      <div style={{
        position: 'absolute',
        bottom: 40,
        left: 40,
        right: 40,
        height: 4,
        backgroundColor: 'rgba(0,0,0,0.1)',
        borderRadius: 2,
      }}>
        <div style={{
          width: `${progress * 100}%`,
          height: '100%',
          backgroundColor: accentColor,
          borderRadius: 2,
        }} />
      </div>
    </AbsoluteFill>
  );
};

const DEFAULT_IMAGES = [
  'quotes/quote1.png',
  'quotes/quote2.png',
  'quotes/quote3.png',
];

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="QuoteReel"
      component={QuoteVideo}
      durationInFrames={DEFAULT_IMAGES.length * CARD_DURATION}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{ images: DEFAULT_IMAGES, brandName: 'BEIA', accentColor: '#F97316' }}
      calculateMetadata={({ props }) => ({
        durationInFrames: Math.max(1, (props.images?.length || 1) * CARD_DURATION),
      })}
    />
  );
};
