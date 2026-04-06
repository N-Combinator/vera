import React, { useState } from 'react';

/**
 * Test React App with Intentional Accessibility Violations
 * Run: vera scan test/ to detect these violations
 */
export default function TestApp() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');

  return (
    <div style={{ padding: '20px', fontFamily: 'Arial, sans-serif' }}>
      {/* VIOLATION: Low color contrast */}
      <header style={{ backgroundColor: '#f0f0f0', color: '#a0a0a0', padding: '20px', marginBottom: '20px' }}>
        <h1>React Accessibility Test App</h1>
        <p>This component contains intentional accessibility violations</p>
      </header>

      {/* VIOLATION: Image missing alt text */}
      <section style={{ marginBottom: '30px' }}>
        <h2>Product Gallery</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '15px' }}>
          <img src="https://via.placeholder.com/150?text=Product+1" />
          <img src="https://via.placeholder.com/150?text=Product+2" />
          <img src="https://via.placeholder.com/150?text=Product+3" />
        </div>
      </section>

      {/* VIOLATION: Form inputs without labels */}
      <section style={{ backgroundColor: 'white', padding: '20px', borderRadius: '5px', marginBottom: '20px' }}>
        <h2>Contact Form (Missing Labels)</h2>
        <input
          type="text"
          placeholder="Enter your name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ width: '100%', padding: '10px', marginBottom: '10px' }}
        />
        <input
          type="email"
          placeholder="Enter your email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{ width: '100%', padding: '10px', marginBottom: '10px' }}
        />
        <button style={{ backgroundColor: '#0066cc', color: 'white', padding: '10px 20px', border: 'none', cursor: 'pointer' }}>
          Submit
        </button>
      </section>

      {/* VIOLATION: Non-semantic interactive element */}
      <div
        onClick={() => alert('Clicked!')}
        style={{
          backgroundColor: '#e0e0e0',
          padding: '15px',
          marginBottom: '20px',
          borderRadius: '5px',
          cursor: 'pointer'
        }}
      >
        I'm a div, not a button! (Click me)
      </div>

      {/* VIOLATION: Missing aria-label on icon button */}
      <button
        style={{
          backgroundColor: '#333',
          color: 'white',
          padding: '10px',
          border: 'none',
          cursor: 'pointer',
          borderRadius: '50%',
          width: '40px',
          height: '40px',
          marginBottom: '20px'
        }}
      >
        ⚙️
      </button>

      {/* VIOLATION: Low contrast button */}
      <button
        style={{
          backgroundColor: '#ffff99',
          color: '#ffff00',
          padding: '10px 20px',
          border: 'none',
          cursor: 'pointer',
          marginBottom: '20px'
        }}
      >
        Low Contrast Button
      </button>

      {/* VIOLATION: Empty heading */}
      <h3></h3>

      {/* VIOLATION: aria-hidden on visible content */}
      <div aria-hidden="true" style={{ backgroundColor: '#fff3cd', padding: '10px', marginBottom: '20px', borderRadius: '3px' }}>
        <strong>Important:</strong> This is hidden from screen readers but visible on screen!
      </div>

      {/* VIOLATION: Heading hierarchy broken */}
      <h1>Main Section</h1>
      <h4>Subsection (should be h2 or h3, not h4)</h4>

      {/* VIOLATION: Broken semantic structure */}
      <div style={{ marginBottom: '20px' }}>
        <div style={{ fontWeight: 'bold', cursor: 'pointer', color: '#0066cc' }}>Navigation Item 1</div>
        <div style={{ fontWeight: 'bold', cursor: 'pointer', color: '#0066cc' }}>Navigation Item 2</div>
        <div style={{ fontWeight: 'bold', cursor: 'pointer', color: '#0066cc' }}>Navigation Item 3</div>
      </div>

      {/* VIOLATION: List without proper markup */}
      <div style={{ backgroundColor: '#f9f9f9', padding: '15px', marginBottom: '20px', borderRadius: '5px' }}>
        <h3>Features (should be ul/li)</h3>
        <div style={{ paddingLeft: '20px' }}>
          <div>✓ Feature 1</div>
          <div>✓ Feature 2</div>
          <div>✓ Feature 3</div>
        </div>
      </div>

      {/* VIOLATION: Focus management issue */}
      <input
        type="text"
        placeholder="Hidden from visual but focusable"
        style={{
          position: 'absolute',
          left: '-10000px',
          width: '1px',
          height: '1px'
        }}
      />

      {/* VIOLATION: Button without accessible name */}
      <button
        style={{
          padding: '10px 20px',
          backgroundColor: '#ddd',
          border: '1px solid #999',
          cursor: 'pointer',
          marginTop: '20px'
        }}
      >
        ✕
      </button>

      <hr style={{ margin: '30px 0' }} />

      <div style={{ backgroundColor: 'white', padding: '20px', borderRadius: '5px' }}>
        <h2>Expected Violations for Vera to Detect:</h2>
        <ul>
          <li>❌ 3 images missing alt text</li>
          <li>❌ Low color contrast in header</li>
          <li>❌ Form inputs without associated labels</li>
          <li>❌ Non-semantic interactive div (should be button)</li>
          <li>❌ Icon button missing aria-label</li>
          <li>❌ Low contrast button (#ffff99 on #ffff00)</li>
          <li>❌ Empty heading (h3)</li>
          <li>❌ aria-hidden on visible important content</li>
          <li>❌ Broken heading hierarchy (h1 → h4 skip)</li>
          <li>❌ Non-semantic navigation (divs instead of nav/button)</li>
          <li>❌ List items as divs instead of ul/li</li>
          <li>❌ Focusable but visually hidden input</li>
          <li>❌ Button with only icon, no accessible name</li>
        </ul>
      </div>

      <footer style={{ marginTop: '40px', paddingTop: '20px', borderTop: '1px solid #ccc', textAlign: 'center', color: '#666' }}>
        <p>Run <code>vera scan test/</code> to find all violations!</p>
      </footer>
    </div>
  );
}
