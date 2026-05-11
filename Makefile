.PHONY: replicate paper clean help

PYTHON ?= python3

help:
	@echo "Targets:"
	@echo "  replicate  Run analyze.py + make_figures.py (uses committed CSVs in data/)"
	@echo "  paper      Compile paper/paper.pdf via pdflatex + bibtex"
	@echo "  clean      Remove generated output/ files and paper/figures/*"

replicate:
	$(PYTHON) code/analyze.py
	$(PYTHON) code/make_figures.py

paper:
	cd paper && pdflatex paper.tex && bibtex paper && pdflatex paper.tex && pdflatex paper.tex

clean:
	rm -f output/per_meeting.csv output/per_day.csv output/regime_summary.json
	rm -f paper/figures/*.pdf paper/figures/*.png
	rm -f paper/paper.aux paper/paper.bbl paper/paper.blg paper/paper.log paper/paper.out paper/paper.toc
