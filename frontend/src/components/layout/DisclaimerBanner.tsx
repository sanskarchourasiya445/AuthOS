import React from 'react'

export const DisclaimerBanner: React.FC = () => {
  return (
    <div className="disclaimer-banner" role="complementary" aria-label="Clinical Governance Disclaimer">
      <div style={{ fontSize: '1.25rem' }} aria-hidden="true">
        ⚖️
      </div>
      <div>
        <strong>Deterministic Clinical Governance:</strong> AuthOS serves exclusively as an evidence provenance and criterion-verification aid. Final prior-authorization determinations require authorized human clinician review.
      </div>
    </div>
  )
}
