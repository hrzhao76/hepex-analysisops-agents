# AGENTS.md - Your Workspace

This folder is home. Treat it that way.

## First Run

If the benchmark request provides `request.data.work_dir` or `request.data.output_dir`
(also exposed as `$HEPEX_SOLVER_WORK_DIR` / `$HEPEX_OUTPUT_DIR`), enter that
directory as the analysis root. Otherwise enter `$HOME/output/`. Install the
environment (spawn subagent to run skill `ana-setup-env`) and then source the
environment.

According to user's intention, select the workflow in `Analysis Workflow References` to start.
- Follow user's configuration e.g. sample, cuts, fitting model, etc if provided.
- If no exactly matched analysis, select the most relevant reference and make your own workflow)

Note: Check if there are already downloaded root files in the analysis root or
the shared cache under `$HOME/output`.

Don't ask permission. Just do it.

## Requirements

- **Code Centralization:** Save all analysis **scripts** and **outputs** in the active analysis root (`$HEPEX_SOLVER_WORK_DIR` / `$HEPEX_OUTPUT_DIR` when provided, otherwise `$HOME/output/`), NOT in any other directory
- **Log to file**: When running scripts/commands, use `tee` to save the log to local file.
**Code Style**
- **Modular**: Save code of each sub-task to separate files/modules, NOT a single file for the whole workflow.
- **Config-Driven**: Use YAML files to define cuts and other parameters.
- **Iterative & Visual**: Output plots at each major step for validation.

## Analysis Workflow References

When a workflow reference below says `Repository/root: $HOME/output`, interpret
that as the active analysis root for this request.

### Higgs to $ZZ^*$ to $4\ell$

<workflow **Higgs to ZZ* to 4l analysis**>
  <description>
    ATLAS Open Data Analysis Pipeline for Rediscovering the Higgs Boson via the golden channel (H -> ZZ* -> 4l).
  </description>
  <sub-task 1. **Install Environment**: Spawn a subagent and load skill `ana-setup-env`>
    - Goal: Install Environment
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Deliverable: Short summary of environment installation
  </sub-task>
  <sub-task 2. **Source Environment**: `source $HOME/.ana-venv/bin/activate` />
  <sub-task 3. **Access Online Data Access & Select Variables**: Spawn a subagent and load skill `ana-create-data-loader`>
    - Goal: Create data loader module file
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Input: the following complete metadata 
    <metadata>
      {
        "release": "2025e-13tev-beta",
        "skim": "exactly4lep",
        "defs": {
            "Data": {"dids": ["data"]},
            "Background Z, ttbar, ttbar+V, VVV": {"dids": [410470, 410155, 410218, 410219, 412043, 364243, 364242, 364246, 364248, 700320, 700321, 700322, 700323, 700324, 700325], "color": "#6b59d3"},
            "Background ZZ*": {"dids": [700600], "color": "#ff0000"},
            "Signal (m_H = 125 GeV)": {"dids": [345060, 346228, 346310, 346311, 346312, 346340, 346341, 346342], "color": "#00cdff"}
        },
        "tree_name": "analysis",
        "variables": ["lep_pt", "lep_eta", "lep_phi", "lep_e", "lep_charge", "lep_type", "trigE", "trigM", "lep_isTrigMatched", "lep_isLooseID", "lep_isMediumID", "lep_isLooseIso", "lep_n"],
        "weight_variables": ["filteff", "kfac", "xsec", "mcWeight", "ScaleFactor_PILEUP", "ScaleFactor_ELE", "ScaleFactor_MUON", "ScaleFactor_LepTRIGGER", "sum_of_weights"]
      }
    </metadata>
    - Deliverable: Short summary of data loader module creation
  </sub-task>
  <sub-task 4. **Define Signal Region (Event Selection, Cuts, Variable Calculation)** >
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-create-event-selector/references/hzz4l_selections.json` />
    <step 2. **You** load and execute skill `ana-create-event-selector` />
  </sub-task>
  <sub-task 5. **Statistical Fitting**>
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-fitting/references/hzz4l_fitting.json` />
    <step 2. **You** load and execute skill `ana-fitting` />
  </sub-task>
</workflow>

### Higgs to $\gamma\gamma$

<workflow **Higgs to $\gamma\gamma$ analysis**>
  <description>
    ATLAS Open Data Analysis Pipeline for Rediscovering the Higgs Boson via the H -> yy channel.
  </description>
  <sub-task 1. **Install Environment**: Spawn a subagent and load skill `ana-setup-env`>
    - Goal: Install Environment
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Deliverable: Short summary of environment installation
  </sub-task>
  <sub-task 2. **Source Environment**: `source $HOME/.ana-venv/bin/activate` />
  <sub-task 3. **Access Online Data Access & Select Variables**: Spawn a subagent and load skill `ana-create-data-loader`>
    - Goal: Create data loader module file
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Input: the following complete metadata 
    <metadata>
      {
        "release": "2025e-13tev-beta",
        "skim": "GamGam",
        "defs": {
            'Data': {'dids': ['data']}
        },
        "tree_name": "analysis",
        "variables": ["photon_pt", "photon_eta", "photon_phi", "photon_e", "photon_isTightID", "photon_ptcone20"]
      }
    </metadata>
    - Deliverable: Short summary of data loader module creation
  </sub-task>
  <sub-task 4. **Define Signal Region (Event Selection, Cuts, Variable Calculation)** >
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-create-event-selector/references/hyy_selections.json` />
    <step 2. **You** load and execute skill `ana-create-event-selector` />
  </sub-task>
  <sub-task 5. **Statistical Fitting**>
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-fitting/references/hyy_fitting.json` />
    <step 2. **You** load and execute skill `ana-fitting` />
  </sub-task>
</workflow>

### Find the Z boson

<workflow **Z to $\mu\mu$ analysis**>
  <description>
    ATLAS Open Data Analysis Pipeline for finding the Z Boson via the di-muon channel.
  </description>
  <sub-task 1. **Install Environment**: Spawn a subagent and load skill `ana-setup-env`>
    - Goal: Install Environment
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Deliverable: Short summary of environment installation
  </sub-task>
  <sub-task 2. **Source Environment**: `source $HOME/.ana-venv/bin/activate` />
  <sub-task 3. **Access Online Data Access & Select Variables**: Spawn a subagent and load skill `ana-create-data-loader`>
    - Goal: Create data loader module file
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Input: the following complete metadata 
    <metadata>
      {
        "release": "2025e-13tev-beta",
        "skim": "2muons",
        "defs": {
            "Data": {"dids": ["data"]}
        },
        "tree_name": "analysis",
        "variables": ["lep_pt", "lep_eta", "lep_phi", "lep_e"]
      }
    </metadata>
    - Deliverable: Short summary of data loader module creation
  </sub-task>
  <sub-task 4. **Define Signal Region (Event Selection, Cuts, Variable Calculation)** >
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-create-event-selector/references/z_mumu_selections.json` />
    <step 2. **You** load and execute skill `ana-create-event-selector` />
  </sub-task>
  <sub-task 5. **Statistical Fitting**>
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-fitting/references/z_mumu_fitting.json` />
    <step 2. **You** load and execute skill `ana-fitting` />
  </sub-task>
</workflow>

### Higgs to $\mu\mu$

<workflow **Higgs to $\mu\mu$ analysis**>
  <description>
    ATLAS Open Data Analysis Pipeline for searching for the rare decay of a Higgs Boson via the H -> \mu^+\mu^- channel.
  </description>
  <sub-task 1. **Install Environment**: Spawn a subagent and load skill `ana-setup-env`>
    - Goal: Install Environment
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Deliverable: Short summary of environment installation
  </sub-task>
  <sub-task 2. **Source Environment**: `source $HOME/.ana-venv/bin/activate` />
  <sub-task 3. **Access Online Data Access & Select Variables**: Spawn a subagent and load skill `ana-create-data-loader`>
    - Goal: Create data loader module file
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Input: the following complete metadata
    <metadata>
      {
        "release": "2025e-13tev-beta",
        "skim": "2muons",
        "defs": {
            "Data": {"dids": ["data"]},
            "Signal Higgs": {"dids": [345106, 345098, 345097], "color": "purple"},
            "Background mu_mu": {"dids": [700323, 700324, 700325], "color": "orange"},
            "Background ttbar": {"dids": [410470], "color": "cyan"}
        },
        "tree_name": "analysis",
        "variables": ["trigM", "lep_isTrigMatched", "lep_n", "met", "lep_type", "lep_pt", "lep_charge", "lep_isMediumID", "lep_isLooseIso", "jet_e", "jet_pt", "jet_btag_quantile", "jet_eta", "jet_phi", "lep_eta", "lep_phi", "lep_e"],
        "weight_variables": ["ScaleFactor_MUON", "ScaleFactor_MuTRIGGER", "ScaleFactor_PILEUP", "ScaleFactor_FTAG", "mcWeight", "sum_of_weights", "xsec", "filteff", "kfac"]
      }
    </metadata>
    - Deliverable: Short summary of data loader module creation
  </sub-task>
  <sub-task 4. **Define Signal Region (Event Selection, Cuts, Variable Calculation)** >
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-create-event-selector/references/hmumu_selections.json` />
    <step 2. **You** load and execute skill `ana-create-event-selector` />
  </sub-task>
  <sub-task 5. **Statistical Plotting & Fitting**>
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-fitting/references/hmumu_fitting.json` />
    <step 2. **You** load and execute skill `ana-fitting` />
  </sub-task>
</workflow>

### ttbar

<workflow **ttbar analysis**>
  <description>
    ATLAS Open Data Analysis Pipeline for Rediscovering the Top-Antitop Quark Pair Production via the semileptonic decay channel.
  </description>
  <sub-task 1. **Install Environment**: Spawn a subagent and load skill `ana-setup-env`>
    - Goal: Install Environment
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Deliverable: Short summary of environment installation
  </sub-task>
  <sub-task 2. **Source Environment**: `source $HOME/.ana-venv/bin/activate` />
  <sub-task 3. **Access Online Data Access & Select Variables**: Spawn a subagent and load skill `ana-create-data-loader`>
    - Goal: Create data loader module file
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Input: the following complete metadata 
    <metadata>
      {
        "release": "2025e-13tev-beta",
        "skim": "1LMET30",
        "defs": {
            "Data": {"dids": ["data"]},
            "Signal ttbar": {"dids": [601495, 410081, 410470], "color": "orange"},
            "Background single_top": {"dids": [601355, 601487, 601627, 601628, 601631, 601761, 601762, 601763, 601764], "color": "cyan"},
            "Background diboson": {"dids": [700488, 700489, 700490, 700491, 700492, 700493, 700495, 700496], "color": "blue"}
        },
        "tree_name": "analysis",
        "variables": ["trigE", "trigM", "lep_isTrigMatched", "lep_n", "lep_pt", "lep_eta", "lep_phi", "lep_e", "lep_type", "met", "met_phi", "jet_n", "jet_pt", "jet_eta", "jet_phi", "jet_e", "jet_btag_quantile"],
        "weight_variables": ["mcWeight", "ScaleFactor_ElTRIGGER", "ScaleFactor_MuTRIGGER", "ScaleFactor_FTAG", "ScaleFactor_ELE", "ScaleFactor_MUON", "ScaleFactor_PILEUP", "sum_of_weights", "xsec", "filteff", "kfac"]
      }
    </metadata>
    - Deliverable: Short summary of data loader module creation
  </sub-task>
  <sub-task 4. **Define Signal Region (Event Selection, Cuts, Variable Calculation)** >
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-create-event-selector/references/ttbar_selections.json` />
    <step 2. **You** load and execute skill `ana-create-event-selector` />
  </sub-task>
  <sub-task 5. **Statistical Plotting & Fitting**>
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-fitting/references/ttbar_fitting.json` />
    <step 2. **You** load and execute skill `ana-fitting` />
  </sub-task>
</workflow>

### WZ to 3l

<workflow **WZ to 3l analysis**>
  <description>
    ATLAS Open Data Analysis Pipeline for exploring WZ diboson production via the fully leptonic final state (WZ -> 3l).
  </description>
  <sub-task 1. **Install Environment**: Spawn a subagent and load skill `ana-setup-env`>
    - Goal: Install Environment
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Deliverable: Short summary of environment installation
  </sub-task>
  <sub-task 2. **Source Environment**: `source $HOME/.ana-venv/bin/activate` />
  <sub-task 3. **Access Online Data Access & Select Variables**: Spawn a subagent and load skill `ana-create-data-loader`>
    - Goal: Create data loader module file
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Input: the following complete metadata 
    <metadata>
      {
        "release": "2025e-13tev-beta",
        "skim": "exactly3lep",
        "defs": {
            "Data": {"dids": ["data"]},
            "Signal": {"dids": [700601], "color": "lightcoral"},
            "Diboson": {"dids": [700493, 700488, 700492, 700600], "color": "slateblue"},
            "Vjets": {"dids": [700323, 700324, 700325, 700470, 700320, 700321, 700322, 700792, 700793, 700794, 700341, 700342, 700343, 700344, 700345, 700346, 700347, 700348, 700349, 700338, 700339, 700340], "color": "green"},
            "other": {"dids": [410470, 410644, 410645, 410658, 410659, 601355, 601352], "color": "orange"}
        },
        "tree_name": "analysis",
        "variables": ["trigDE", "trigDM", "TriggerMatch_DILEPTON", "lep_isTightID", "lep_isLooseIso", "lep_topoetcone20", "lep_ptvarcone30", "lep_n", "lep_pt", "lep_eta", "lep_phi", "lep_charge", "lep_type", "met", "met_phi", "lep_e"],
        "weight_variables": ["mcWeight", "sum_of_weights", "ScaleFactor_ELE", "ScaleFactor_MUON", "ScaleFactor_MLTRIGGER", "ScaleFactor_PILEUP", "xsec", "filteff", "kfac"]
      }
    </metadata>
    - Deliverable: Short summary of data loader module creation
  </sub-task>
  <sub-task 4. **Define Signal Region (Event Selection, Cuts, Variable Calculation)** >
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-create-event-selector/references/wz3l_selections.json` />
    <step 2. **You** load and execute skill `ana-create-event-selector` />
  </sub-task>
  <sub-task 5. **Statistical Plotting & Fitting**>
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-fitting/references/wz3l_fitting.json` />
    <step 2. **You** load and execute skill `ana-fitting` />
  </sub-task>
</workflow>

### Higgs to bb

<workflow **Higgs to bb analysis**>
  <description>
    ATLAS Open Data Analysis Pipeline for searching for the Higgs Boson via the H -> bb channel (0-lepton channel).
  </description>
  <sub-task 1. **Install Environment**: Spawn subagent to run skill `ana-setup-env`>
    - Goal: Install Environment
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Deliverable: Short summary of environment installation
  </sub-task>
  <sub-task 2. **Source Environment**: `source $HOME/.ana-venv/bin/activate` />
  <sub-task 3. **Access Online Data Access & Select Variables**: Spawn subagent to run skill `ana-create-data-loader`, pass the following complete metadata to the subagent prompt>
    - Goal: Create data loader module file
    - Repository/root: `$HOME/output`
    - Actions allowd: read files, edit files, run all commands
    - Input: the following complete metadata 
    <metadata>
      {
        "release": "2025e-13tev-beta",
        "skim": "2bjets",
        "defs": {
            "Data": {"dids": ["data"]},
            "Signal": {"dids": [345056, 345058, 345949, 346311, 346312], "color": "red"},
            "Background ttbar": {"dids": [410470, 410471], "color": "yellow"},
            "Background Single top": {"dids": [410644, 410645, 410658, 410659, 601624, 601628], "color": "orange"},
            "Background V+jets": {"dids": [700320, 700321, 700322, 700323, 700324, 700325, 700335, 700336, 700337, 700338, 700339, 700340, 700341, 700342, 700343, 700344, 700345, 700346, 700347, 700348, 700349, 700467, 700468, 700469, 700470, 700471, 700472, 700792, 700793, 700794], "color": "blue"},
            "Background Diboson": {"dids": [700488, 700489, 700490, 700491, 700492, 700493, 700494, 700495, 700496, 700195, 700196, 700199, 700200, 700201], "color": "grey"}
        },
        "tree_name": "analysis",
        "variables": ["jet_jvt", "jet_n", "jet_pt", "jet_eta", "jet_phi", "jet_e", "met", "met_phi", "trigMET", "jet_btag_quantile", "lep_isLooseIso", "lep_d0sig", "lep_z0", "lep_type", "lep_eta", "lep_e", "lep_pt", "lep_isTightID", "lep_isLooseID"],
        "weight_variables": ["xsec", "mcWeight", "ScaleFactor_PILEUP", "ScaleFactor_FTAG", "ScaleFactor_JVT", "filteff", "kfac", "sum_of_weights"]
      }
      </metadata>
    - Deliverable: Short summary of data loader module creation
  </sub-task>
  <sub-task 4. **Define Signal Region (Event Selection & Cuts, Variable Calculation)**>
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-create-event-selector/references/hbb_selections.json` />
    <step 2. **You** directly run skill `ana-create-event-selector` />
  </sub-task>
  <sub-task 5. **Statistical Fitting**>
    <step 1. Read complete content of file `$HOME/.openharness/skills/ana-fitting/references/hbb_fitting.json` />
    <step 2. **You** directly run skill `ana-fitting` />
  </sub-task>
</workflow>

## Output Format

If user specificlly request formatted JSON and MD outputs:
1. Read file: `$HOME/ouptut/submission_contract.json` or `$HOME/submission_contract.json`
2. Strictly follow the format of submission_contract.json, fill all the fields, DO NOT skip any fileds. If no relevant content, fill in "N/A" or "None".

## Make It Yours

This is a starting point. Add your own conventions, style, and rules as you figure out what works.

### Troubleshooting Checklist

1.  **Cutflow Mismatch**: 
    - Check **Lepton Isolation**: Did you veto based on `lep_isLooseIso` and `lep_z0 < 0.5`?
    - Check **B-tagging**: Is the quantile threshold correct for the targeted efficiency?
2.  **Mass Peak Offset**:
    - **PtReco Balance**: Applying PtReco to both jets in a $H \to bb$ search can shift the peak to $\sim 140$ GeV. Re-calibrate to leading jet or use standard reference constants.
    - **Pure Signal Mean vs S+B Fit**: Never trust the weighted mean of the signal MC alone (tails pull it high). Always use a **Signal + Background** fit on data.
3.  **Fit Failure**:
    - **Background Model**: Simple polynomials may fail at low-mass thresholds. Use **Bernstein Polynomials** or **Exponential-Polynomial** combinations for complex thresholds.
