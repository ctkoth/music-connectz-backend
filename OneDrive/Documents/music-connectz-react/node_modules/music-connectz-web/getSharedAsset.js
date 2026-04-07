import { Image } from 'react-native';

// Utility for web to import shared assets
export function getSharedAsset(assetName) {
  return `/packages/shared/assets/${assetName}`;
}

// Example usage in a React component:
// <img src={getSharedAsset('artist.png')} alt="Artist" />
