"use client";

import React, { ReactNode } from 'react';

/**
 * ScreenAtmosphere
 * 
 * A foundational layout component that establishes the "Liquid Obsidian" 
 * baseline environment for the application.
 * 
 * The Physics & Visual Engine:
 * Layer 1 is a pure dark anchor (#0a0a0a) that prevents light-bleed.
 * Layer 2 is an SVG `feTurbulence` noise mask, which creates an ultra-premium
 * cinematic film grain. By setting it to `mix-blend-overlay` and low opacity,
 * it gives depth to the flat color without hindering legibility.
 * 
 * @param children - The main application content to be rendered over the atmosphere.
 */
export default function ScreenAtmosphere({ children }: { children: ReactNode }) {
  return (
    <div className="relative min-h-screen w-full bg-[#0a0a0a] text-white selection:bg-purple-500/30 overflow-hidden">
      
      {/* 
        Layer 2: The Cinematic Grain Overlay
        We use an inline SVG to generate a fractal noise pattern. 
        It is absolutely positioned, covers the screen, and ignores pointer events 
        so it doesn't block clicks. 
      */}
      <div className="absolute inset-0 z-0 pointer-events-none opacity-20 mix-blend-overlay">
        <svg width="100%" height="100%">
          <filter id="noiseFilter">
            <feTurbulence 
              type="fractalNoise" 
              baseFrequency="0.65" 
              numOctaves="3" 
              stitchTiles="stitch" 
            />
          </filter>
          <rect width="100%" height="100%" filter="url(#noiseFilter)" />
        </svg>
      </div>

      {/* Layer 3: The Content */}
      <div className="relative z-10 w-full h-full">
        {children}
      </div>
    </div>
  );
}
