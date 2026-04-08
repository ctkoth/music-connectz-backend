import React, { useEffect, useRef } from 'react';

export default function GoogleMapWithRadius({ radiusMeters = 1000 }) {
  const mapRef = useRef(null);

  useEffect(() => {
    if (!window.google || !window.google.maps) return;
    if (!mapRef.current) return;

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords;
        const map = new window.google.maps.Map(mapRef.current, {
          center: { lat: latitude, lng: longitude },
          zoom: 14,
        });
        new window.google.maps.Marker({
          position: { lat: latitude, lng: longitude },
          map,
          title: 'You are here',
        });
        new window.google.maps.Circle({
          strokeColor: '#4285F4',
          strokeOpacity: 0.8,
          strokeWeight: 2,
          fillColor: '#4285F4',
          fillOpacity: 0.2,
          map,
          center: { lat: latitude, lng: longitude },
          radius: radiusMeters,
        });
      },
      (err) => {
        // fallback to NYC if denied
        const map = new window.google.maps.Map(mapRef.current, {
          center: { lat: 40.7128, lng: -74.0060 },
          zoom: 12,
        });
      }
    );
  }, [radiusMeters]);

  useEffect(() => {
    if (!window.google || !window.google.maps) {
      // Prevent duplicate script injection
      if (!document.querySelector('script[src^="https://maps.googleapis.com/maps/api/js"]')) {
        const script = document.createElement('script');
        script.src = `https://maps.googleapis.com/maps/api/js?key=${process.env.REACT_APP_GOOGLE_MAPS_API_KEY}`;
        script.async = true;
        script.onload = () => {};
        document.body.appendChild(script);
      }
    }
  }, []);

  return (
    <div style={{ width: '100%', height: 400, borderRadius: 12, overflow: 'hidden', margin: '32px 0' }}>
      <div ref={mapRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
}
