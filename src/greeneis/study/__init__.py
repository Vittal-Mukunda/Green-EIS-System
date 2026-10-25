"""The study harness: tests H1-H5 of docs/RESEARCH_DESIGN.md on any data in the case-table shape.

It never decides what the data are. `cases.py` defines the shape; loaders for real data (ASI, BEE audits)
produce it; `synthetic.py` produces labelled test data so the pipeline can be exercised. Results from
synthetic data say nothing about the world and are marked as such in every output.
"""
