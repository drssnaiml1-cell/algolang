# Computational target discovery standards

- Network prioritisation must be validated: hide known disease genes, then measure how many reappear among the
  top candidates. Report recovery and AUROC.
- Always run a negative control (random seed proteins of the same size). If the control looks as convincing as
  the real seeds, the result reflects network structure, not disease biology.
- Pathway enrichment uses a hypergeometric test with Benjamini–Hochberg false-discovery-rate control (q < 0.05).
- Wet-lab validation needs two approvals (principal investigator and lab manager), because reagents and
  instrument time are limited.
- Open reading frames shorter than 150 codons are not called protein-coding: random GC-rich DNA produces long
  ORFs by chance.
