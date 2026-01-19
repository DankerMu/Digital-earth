import { Cartesian3, Math as CesiumMath, type Viewer } from 'cesium';
import { useEffect, useRef } from 'react';

type CompassControlProps = {
  viewer: Viewer;
};

export function CompassControl({ viewer }: CompassControlProps) {
  const needleRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    const needleEl = needleRef.current!;

    const update = () => {
      const degrees = CesiumMath.toDegrees(viewer.camera.heading);
      needleEl.style.transform = `rotate(${degrees}deg)`;
    };

    viewer.scene.postRender.addEventListener(update);
    update();

    return () => {
      viewer.scene.postRender.removeEventListener(update);
    };
  }, [viewer]);

  const handleClick = () => {
    const destination = Cartesian3.clone(viewer.camera.position);
    viewer.camera.flyTo({
      destination,
      orientation: {
        heading: 0,
        pitch: viewer.camera.pitch,
        roll: 0
      },
      duration: 0.3
    });
  };

  return (
    <button
      type="button"
      aria-label="Compass"
      className="compassButton"
      onClick={handleClick}
    >
      <span ref={needleRef} className="compassNeedle" aria-hidden="true" />
      <span className="compassLabel" aria-hidden="true">
        N
      </span>
    </button>
  );
}
