import React from "react";
import { Composition } from "remotion";
import { Reel, ReelProps, defaultProps } from "./Reel";

export const Root: React.FC = () => (
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
);
