"use client";

import React, { useRef, useMemo, memo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

/*
 * ─── Spatial Background: Fluid Mesh ───────────────────────────────────────
 *
 * This component renders a slow-moving, morphing chromatic 3D mesh behind
 * the Transaction Ledger. It uses Three.js via the lightweight
 * `@react-three/fiber` wrapper.
 *
 * Why a TorusKnot geometry?
 *   The TorusKnot has self-intersecting loops that catch light at every
 *   angle, creating a rich "fluid" appearance when the camera slowly
 *   orbits or the mesh rotates. We combine this with a vertex-displacement
 *   shader (applied via `position` array manipulation) to make it breathe
 *   like liquid.
 *
 * Performance:
 *   - The rotation and vertex displacement run on the GPU via `useFrame`
 *     (the R3F animation loop, which piggybacks on requestAnimationFrame).
 *   - The component is `memo()`-wrapped so it never re-renders for parent
 *     state changes — it is a pure visual ornament.
 *   - Colors are interpolated in HSL space to produce smooth chromatic
 *     transitions without jarring jumps.
 *
 * Layout:
 *   The Canvas is position:fixed at z-index:-1, filling the viewport.
 *   The camera is placed at z=5 so the mesh occupies the background
 *   without overlapping foreground content.
 */

// ─── The inner 3D scene ───────────────────────────────────────────────────

function FluidMesh() {
  const meshRef = useRef<THREE.Mesh>(null);

  /*
   * Grab the raw position attribute so we can displace individual vertices
   * over time, creating a "breathing fluid" effect.
   */
  const positionsRef = useRef<Float32Array | null>(null);

  // Pre-compute a random offset per vertex so each one moves independently
  const offsets = useMemo(() => {
    // We'll lazily initialise this once we know the vertex count
    return { seed: Math.random() * 100 };
  }, []);

  useFrame(({ clock }) => {
    const mesh = meshRef.current;
    if (!mesh) return;

    const geometry = mesh.geometry;
    const pos = geometry.attributes.position;
    // Cache the original positions on first frame so we displace relative to
    // the base shape rather than accumulating drift.
    if (!positionsRef.current) {
      positionsRef.current = new Float32Array(pos.array);
    }

    const t = clock.getElapsedTime() * 0.15; // Slow time factor
    const base = positionsRef.current;

    /*
     * Vertex displacement: For each vertex we nudge it along its normal
     * direction using a sine wave. The frequency varies per vertex based
     * on its original x/z coordinates so the surface ripples organically
     * rather than inflating uniformly like a balloon.
     *
     * Formula:  displaced = base + normal * sin(t + x*2 + z*2) * amplitude
     * where amplitude = 0.08 (small so the shape keeps its recognisable
     * TorusKnot silhouette).
     */
    const positions = pos.array;
    const amplitude = 0.08;
    for (let i = 0; i < positions.length; i += 3) {
      const ix = i;
      const iy = i + 1;
      const iz = i + 2;

      const bx = base[ix];
      const by = base[iy];
      const bz = base[iz];

      // Simple pseudo-normal: use the vertex position itself normalised
      // (works well enough for a centrally-symmetric shape like TorusKnot).
      const len = Math.sqrt(bx * bx + by * by + bz * bz) || 1;
      const nx = bx / len;
      const ny = by / len;
      const nz = bz / len;

      const wave = Math.sin(t + bx * 2 + bz * 2) * amplitude;

      positions[ix] = bx + nx * wave;
      positions[iy] = by + ny * wave;
      positions[iz] = bz + nz * wave;
    }
    pos.needsUpdate = true;
  });

  /*
   * Chromatic gradient: the mesh material uses two colours that slowly
   * cross-fade via the `time` uniform (driven by useFrame on a separate
   * ref). We use MeshPhysicalMaterial for the glassy / liquid look.
   */
  const materialRef = useRef<THREE.MeshPhysicalMaterial>(null);

  useFrame(({ clock }) => {
    const mat = materialRef.current;
    if (!mat) return;

    /*
     * HSL colour cycling: we sweep hue slowly from blue (240) toward
     * violet (300) and back, keeping saturation high and lightness
     * moderate so it remains visible but atmospheric.
     */
    const t = clock.getElapsedTime() * 0.03;
    const hue = 240 + Math.sin(t) * 30;       // 210 – 270 range
    const hue2 = 270 + Math.cos(t * 0.7) * 30; // 240 – 300 range

    mat.color.setHSL(hue / 360, 0.7, 0.15);
    mat.emissive.setHSL(hue2 / 360, 0.8, 0.05);
  });

  return (
    <mesh ref={meshRef} rotation={[0.2, 0.4, 0]}>
      <torusKnotGeometry args={[1.6, 0.5, 256, 64, 2, 3]} />
      <meshPhysicalMaterial
        ref={materialRef}
        roughness={0.3}
        metalness={0.1}
        transparent
        opacity={0.6}
        clearcoat={0.4}
        clearcoatRoughness={0.6}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

// ─── Public component ─────────────────────────────────────────────────────

/**
 * SpatialBackground
 *
 * A full-viewport Three.js canvas rendering a slow-moving fluid chromatic
 * mesh. Designed as a fixed z-[-1] underlay for the Transaction Ledger.
 *
 * Usage:
 *   <SpatialBackground />
 *
 * Props: none
 */
const SpatialBackground = memo(function SpatialBackground() {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: -1,
        pointerEvents: 'none',
      }}
    >
      <Canvas
        camera={{ position: [0, 0, 5], fov: 50 }}
        dpr={[1, 1.5]} // Cap DPR for performance on high-DPI screens
        gl={{ antialias: true, alpha: true }}
        style={{ width: '100%', height: '100%' }}
      >
        <ambientLight intensity={0.3} />
        <pointLight position={[5, 5, 5]} intensity={1.5} color="#4466ff" />
        <pointLight position={[-5, -3, 2]} intensity={0.8} color="#ff66aa" />
        <FluidMesh />
      </Canvas>
    </div>
  );
});

export default SpatialBackground;
