install:
	@echo "➡️ Installing Python app dependencies..."
	python3 -m pip install -r requirements.txt

	@echo "➡️ Installing Python dev dependencies..."
	python3 -m pip install -r requirements-dev.txt

upgrade:
	@echo "➡️ Upgrading pip..."
	python3 -m pip install --upgrade pip

	@echo "➡️ Upgrading Python app dependencies..."
	python3 -m pur -r requirements.txt

	@echo "➡️ Upgrading Python dev dependencies..."
	python3 -m pur -r requirements-dev.txt

test:
	@echo "➡️ Running Black..."
	python3 -m black --check .

	@echo "➡️ Running deptry..."
	python3 -m deptry \
		--per-rule-ignores "DEP002=faiss-cpu|unstructured" \
		.

lint:
	@echo "➡️ Running Black..."
	python3 -m black .

dev:
	python3 -m streamlit run main.py
