"""Preset Akademika product catalog for the Streamlit content builder."""

import re


def clean_id(value: str) -> str:
    """Return a lowercase underscore identifier from product/category text."""
    value = value.strip().lower()
    value = value.replace('&', ' and ')
    value = re.sub(r'[^a-z0-9]+', '_', value)
    return re.sub(r'_+', '_', value).strip('_')


def clean_product_id(product_name: str) -> str:
    """Generate clean product IDs from product names and model/code prefixes."""
    name = product_name.strip()
    prefix = name.split(':', 1)[0].strip() if ':' in name else ''
    model_match = re.search(r'\(Model:\s*([^\)]+)\)', name, re.IGNORECASE)

    if prefix and len(prefix) <= 24 and re.search(r'[A-Z0-9]', prefix):
        return clean_id(prefix)
    if model_match:
        return clean_id(model_match.group(1))
    return clean_id(name)


PRODUCT_CATALOG = [
    {
        'categoryName': 'Analog Communication',
        'categoryId': 'analog_communication',
        'products': [
            'ACS: Analog Communication Training System',
            'ACL-AM: Amplitude Modulation Transmitter Kit',
            'ACL-AD: Amplitude Demodulation Receiver Kit',
            'ACL-FM: Frequency Modulation Transmitter Kit',
            'ACL-FD: Frequency Demodulation Receiver Kit',
            'ACL-NP: Noise Power Spectral Density Measurement Kit',
            'ACL-FDM: FDM Transmitter / Receiver Kit',
            'ACL-FIL: Filters/Noise and Audio Amplifier Kit',
            'ACL-FS: Fourier Synthesis Kit',
        ],
    },
    {
        'categoryName': 'Artificial Intelligence and Machine Learning',
        'categoryId': 'artificial_intelligence_and_machine_learning',
        'products': ['Artificial Intelligence and Machine Learning Laboratory'],
    },
    {
        'categoryName': 'Basic Electronics',
        'categoryId': 'basic_electronics',
        'products': [
            'BEL-COT: Discrete Components Trainer',
            'BEL-TAT: Transistor Application Trainer',
            'BEL-OPT: Op-Amp Trainer',
            'BEL-NBT: Network And Bridges Trainer',
            'BEL-ADA: Analog to Digital and Digital to Analog Converter Trainer',
            'BEL-LIT: Linear IC Trainer',
            'BEL-DIT: Digital IC Trainer',
            'BEL-ADT: Analog and Digital Trainer',
            'BEL-PET: Power Electronics Trainer',
        ],
    },
    {
        'categoryName': 'Computer Networks',
        'categoryId': 'computer_networks',
        'products': [
            'CYBER SECURITY & ETHICAL HACKING TRAINER (Model: NL-CSHT)',
            'LOCAL AREA NETWORK TRAINER (Model: NL-LTS)',
            'PC HARDWARE TRAINER (Model: VTPC)',
            'Digital Forensics Laboratory',
            'NL-NST: Computer Networks and Cyber Security WorkBench',
            'NL-LTS with LSIM: Local Area Network Trainer with Protocol Simulator And Analysis Software',
        ],
    },
    {
        'categoryName': 'Controls and Instrumentation',
        'categoryId': 'controls_and_instrumentation',
        'products': [
            'PCB-B: Basic PCB Manufacturing Lab',
            'CL-PLC: Programmable Logic Controller Trainer',
        ],
    },
    {
        'categoryName': 'Digital Communication',
        'categoryId': 'digital_communication',
        'products': [
            'DCS-B: Basic Digital Communication Training System',
            'DCS-A: Advanced Digital Communication Training System',
            'SDR-B: Software Defined Radio',
        ],
    },
    {
        'categoryName': 'Embedded System',
        'categoryId': 'embedded_system',
        'products': [
            'VL-FPGA-B: FPGA Trainer Kit',
            'PL-ARM: Embedded Training Kit',
            'PL-DSP: DSP Trainer Kit',
        ],
    },
    {
        'categoryName': 'Fiber Optics',
        'categoryId': 'fiber_optics',
        'products': [
            'FOL-PHYSICS: Physics Of Fiber Optic Lab',
            'FOL-B-P: Fiber Optic Communication Trainer',
            'FOL-MI: Michelson Interferometer',
            'FOL-MZM: Mach Zehnder Interferometer',
            'Holographic Lab',
            'FOL-WAVE: Construction And Study of Mode Properties of Planar Waveguide',
            'FOL-A-F: Advanced Fiber Optic Communication Trainer',
            'FOL-M-GP: Fiber Optic Trainer Kit for Glass and Plastic Fiber with Optical Power Meter',
            'FOL-DUAL: Dual Wavelength Fiber Optic Laser Source And Detector Module',
            'FOL-PASSIVE: Fiber Optic Passive Component Module',
            'FOL-FIBER: Single Mode Fiber Optic Cable Module',
            'FOL-CDC: Chromatic Dispersion Module',
            'FOL-CWDM: Coarse WDM and Bragg Grating Module',
            'FOL-OTDR: Optical Time Domain Reflectometer with Add-On Event Module',
            'FOL-CSK: Fiber Optic Test Equipment for Connectorisation and Splicing',
            'FOL-OSA: Optical Spectrum Analyzer',
            'FOL-EDFA: Erbium Doped Fiber Amplifier Module',
            'FTTH Trainer',
        ],
    },
    {
        'categoryName': 'IoT Laboratory',
        'categoryId': 'iot_laboratory',
        'products': ['IoT Laboratory'],
    },
    {
        'categoryName': 'RF / Microwave / Antenna',
        'categoryId': 'rf_microwave_antenna',
        'products': [
            'SA3600TG: 9KHz to 3.6GHz Spectrum Analyser with Tracking Generator',
            'VNA 6000: Vector Network Analyzer Add-on to our Model RFL-AMS-A',
            'RFL-AMS-A: 4 GHz Motorized Antenna Trainer',
            'RFL-MCT-A-3G: Advanced Microstrip Component Trainer (3GHz)',
            'RFL-MMTLT: Motorised Microstrip Transmission Line Trainer',
            'RFL-RFT: RF Circuit Trainer',
            'RFL-RFGD: 3GHz RF Generator and Detector',
        ],
    },
    {
        'categoryName': 'Test and Measuring Instruments',
        'categoryId': 'test_and_measuring_instruments',
        'products': [
            'DDS-25: 25MHz Dual Channel DDS Function Generator',
            'DSO100C1G: 100MHz 2 Channel Digital Storage Oscilloscope',
        ],
    },
    {
        'categoryName': 'VLSI',
        'categoryId': 'vlsi',
        'products': [
            'VL-ZedBOARD: Zynq-7000 Development Board + PMOD + PCAM',
            'VL-KRIA: EDGE FPGA DEVELOPMENT BOARD',
            'VL CPLD BASIC CPLD DEVELOPMENT LEARNING BOARD',
            'Advance Spartan-7 FPGA Platform for VLSI Lab',
            'InAS FPGA ARM/SOC Development Board with Expansion',
            'VL-SIEN: SIEN FPGA DEVELOPMENT BOARD',
        ],
    },
]


def get_categories():
    return PRODUCT_CATALOG


def get_category_names():
    return [category['categoryName'] for category in PRODUCT_CATALOG]


def get_category(category_name: str):
    return next((category for category in PRODUCT_CATALOG if category['categoryName'] == category_name), None)


def get_products(category_name: str):
    category = get_category(category_name)
    return category['products'] if category else []


def get_product_defaults(category_name: str, product_name: str):
    category = get_category(category_name) or {'categoryName': category_name, 'categoryId': clean_id(category_name)}
    product_id = clean_product_id(product_name)
    return {
        'categoryName': category['categoryName'],
        'categoryId': category['categoryId'],
        'productName': product_name,
        'productId': product_id,
        'manualId': product_id,
    }


def product_count():
    return sum(len(category['products']) for category in PRODUCT_CATALOG)
