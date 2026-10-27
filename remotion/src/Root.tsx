import React from "react";
import { Composition } from "remotion";
import { Reel, ReelProps, defaultProps } from "./Reel";
import { Doc, DocProps, docDefaults } from "./Doc";

export const Root: React.FC = () => (
  <>
    <Composition
      id="Reel"
      component={Reel}
      fps={30}
      width={1080}
      height={1920}
      durationInFrames={300}
      defaultProps={defaultProps}
      calculateMetadata={({ props }) => ({
        durationInFrames: Math.max(30, Math.round((props as ReelProps).total * 30)),
      })}
    />
    <Composition
      id="Doc"
      component={Doc}
      fps={30}
      width={1920}
      height={1080}
      durationInFrames={300}
      defaultProps={docDefaults}
      calculateMetadata={({ props }) => ({
        durationInFrames: Math.max(30, Math.round((props as DocProps).total * 30)),
      })}
    />
  </>
);
