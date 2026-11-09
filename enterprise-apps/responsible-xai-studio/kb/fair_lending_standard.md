# Fair-lending model standard

- Protected attributes (gender, caste, religion and the audited group) are never model inputs, and features
  that correlate strongly with them (area indices, some postcodes) are treated as proxies and removed.
- Disparate impact must be at least 0.8 (four-fifths rule) and the equal-opportunity gap (approval among
  applicants who repaid) at most 0.10. Calibration error must be similar across groups.
- Every decline comes with an explanation of its main drivers and actionable recourse; age and area are never
  suggested changes.
- Certification needs two different model-risk approvers. Biased models are remediated and re-audited.
