import React from 'react';


import { useState } from 'react';

const BattlesTab = () => {

  const [wager, setWager] = useState(0);
  const [battleType, setBattleType] = useState('individual');

  return (
    <div className="battles-tab">
      <h1>Battles</h1>
      <p>Collaborate and compete with other teams! Start a new battle or join an existing one.</p>

      <div style={{ margin: '24px 0', padding: 16, border: '1px solid #ccc', borderRadius: 8, maxWidth: 400 }}>
        <h2>Battle Type</h2>
        <label style={{ marginRight: 18 }}>
          <input
            type="radio"
            name="battle-type"
            value="individual"
            checked={battleType === 'individual'}
            onChange={() => setBattleType('individual')}
          />{' '}
          Individual Artist
        </label>
        <label>
          <input
            type="radio"
            name="battle-type"
            value="group"
            checked={battleType === 'group'}
            onChange={() => setBattleType('group')}
          />{' '}
          Group Artist (collab with more than one artist)
        </label>
      </div>

      <div style={{ margin: '24px 0', padding: 16, border: '1px solid #ccc', borderRadius: 8, maxWidth: 400 }}>
        <h2>Wager Setup</h2>
        <label>
          Royalty Wager Amount:
          <input
            type="number"
            min="0"
            value={wager}
            onChange={e => setWager(Number(e.target.value))}
            style={{ marginLeft: 8, width: 80 }}
          />
        </label>
        <div style={{ marginTop: 16, color: '#555' }}>
          <strong>Type:</strong> Only "By Being Greater" is allowed.<br />
          <strong>Note:</strong> All parties must accept. Wagers are charged and rewarded from royalties.<br />
          <strong>Legal:</strong> Battles involving money/royalties require video and ID verification. Free battles are open to all users, no verification or gambling exposure required.
        </div>
      </div>
      {/* Placeholder for battles UI */}
    </div>
  );
};

export default BattlesTab;
