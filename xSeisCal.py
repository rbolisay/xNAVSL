#!/usr/bin/env python2
# -*- coding: utf-8 -*-
import Tkinter as tk
import tkMessageBox # Import message box module
import math # Import math for sqrt and pi

# --- Constants ---
# Speed
METERS_PER_SECOND_PER_KNOT = 0.514444
KNOTS_PER_METER_PER_SECOND = 1.0 / METERS_PER_SECOND_PER_KNOT
KMH_PER_MPS = 3.6
MPS_PER_KMH = 1.0 / KMH_PER_MPS
# Angle/Time
RADS_PER_DEG = math.pi / 180.0
DEG_PER_RADS = 180.0 / math.pi
SECS_PER_MIN = 60.0
# Distance
METERS_PER_KM = 1000.0
KM_PER_METER = 1.0 / METERS_PER_KM
METERS_PER_NM = 1852.0 # Nautical Mile
NM_PER_METER = 1.0 / METERS_PER_NM
METERS_PER_MI = 1609.344 # Statute Mile
MI_PER_METER = 1.0 / METERS_PER_MI
# Other
TOLERANCE = 1e-9 # Tolerance for floating point zero checks
NIPPON_BLUE_AURA = '#B4C8E1' # GUI Background Color
BUTTON_BG_COLOR = '#8DA9CC'  # Button Background Color
READONLY_BG = NIPPON_BLUE_AURA # Updated readonly background
BUTTON_FG = 'black' # Button text color

# --- Data Structures for Parameters ---
# Calculator 1: Shot Distance/Time/Speed
shot_params_config = [
    {'name': 'bsp_knots', 'label': 'BSP (knots):',      'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'distance',  'label': 'Shot Distance (m):','chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'time',      'label': 'Shot Time (s):',    'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
]
# Calculator 2: Xline/Inline Feathering
feather_params_config = [
    {'name': 'x_dist',  'label': 'Xline distance (m):', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'i_dist',  'label': 'Inline distance (m):','chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'f_bsp',   'label': 'BSP (knots):',        'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'v_across','label': 'Velocity Across (knots):', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
]
# Calculator 3: Turn Rate/Radius
turn_params_config = [
    {'name': 'radius_km', 'label': 'Turn Radius (km):', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'rate_deg_min','label': 'Turn Rate (deg/min):','chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 't_bsp',     'label': 'BSP (knots):',      'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
]
# Calculator 4: Equipment Turn Water Speed
equip_turn_params_config = [
    {'name': 'vessel_radius', 'label': 'Vessel Turn Radius (m):',      'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'vessel_speed',  'label': 'Vessel Water Speed (knots):', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'equip_width',   'label': 'Equipment Width (m):',        'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'outer_speed',   'label': 'Outer Equipment WSP:', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'inner_speed',   'label': 'Inner Equipment WSP:', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
]
# Calculator 5: BSP Converter
bsp_conv_params_config = [
    {'name': 'bsp_knots_conv', 'label': 'BSP (knots):', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'bsp_ms_conv',    'label': 'BSP (m/s):',   'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'bsp_kmh_conv',   'label': 'BSP (km/hr):', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
]
# Calculator 6: Distance Converter
dist_conv_params_config = [
    {'name': 'dist_m',  'label': 'Distance (m):',  'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'dist_nm', 'label': 'Distance (NM):', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'dist_km', 'label': 'Distance (km):', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
    {'name': 'dist_mi', 'label': 'Distance (mi):', 'chk_var': None, 'in_var': None, 'chk_widget': None, 'entry_widget': None},
]


# --- Checkbox State Update Callback ---
def update_checkbox_states(calculator_type):
    """
    Called when any checkbox state changes.
    Sets Entry state to NORMAL (checked) or READONLY (unchecked).
    Enables/disables Checkboxes based on selection count limit.
    """
    params_list = None
    required_selections = 0

    if calculator_type == 'shot':
        params_list = shot_params_config
        required_selections = 2
    elif calculator_type == 'feather':
        params_list = feather_params_config
        required_selections = 3
    elif calculator_type == 'turn':
        params_list = turn_params_config
        required_selections = 2
    elif calculator_type == 'equip_turn':
        params_list = equip_turn_params_config
        required_selections = 3
    elif calculator_type == 'bsp_conv':
        params_list = bsp_conv_params_config
        required_selections = 1
    elif calculator_type == 'dist_conv':
        params_list = dist_conv_params_config
        required_selections = 1
    else:
        return # Unknown type

    if params_list is None: return

    current_selection_count = 0
    # First Pass: Update Entry states and count selections
    for param in params_list:
        entry_widget = param.get('entry_widget')
        chk_var = param.get('chk_var')
        if chk_var is None or entry_widget is None: continue

        is_checked = chk_var.get() == 1
        if is_checked:
            current_selection_count += 1
            entry_widget.config(state=tk.NORMAL, bg='white')
        else:
            entry_widget.config(state='readonly', readonlybackground=READONLY_BG)

    # Second Pass: Update Checkbox states based on count
    if current_selection_count >= required_selections:
        for param in params_list:
            chk_widget = param.get('chk_widget')
            chk_var = param.get('chk_var')
            if chk_widget and chk_var:
                if chk_var.get() == 0: chk_widget.config(state=tk.DISABLED)
                else: chk_widget.config(state=tk.NORMAL)
    else:
        for param in params_list:
            chk_widget = param.get('chk_widget')
            if chk_widget: chk_widget.config(state=tk.NORMAL)


# --- Calculation Logic ---

def calculate_shot():
    checked_items = []
    unchecked_items = []
    for param in shot_params_config:
        if param['chk_var'].get() == 1: checked_items.append(param)
        else: unchecked_items.append(param)

    if len(checked_items) != 2 or len(unchecked_items) != 1:
        tkMessageBox.showwarning("Selection Error", "Shot Calc: Please select exactly two parameters as input.")
        return

    target_param = unchecked_items[0]
    target_name = target_param['name']
    provided_values = {}
    try:
        for param in checked_items:
            name = param['name']
            val_str = param['in_var'].get()
            if not val_str:
                 tkMessageBox.showerror("Input Error", "Shot Calc: Selected input field '{}' is empty.".format(param['label']))
                 target_param['in_var'].set("")
                 return
            provided_values[name] = float(val_str)
    except ValueError:
        tkMessageBox.showerror("Input Error", "Shot Calc: Invalid numeric value in one of the selected fields.")
        target_param['in_var'].set("")
        return
    except Exception as e:
        tkMessageBox.showerror("Error", "Shot Calc: Error reading inputs: {}".format(e))
        target_param['in_var'].set("")
        return

    calculated_value = None
    input_names = set(provided_values.keys())
    try:
        knots = provided_values.get('bsp_knots')
        dist = provided_values.get('distance')
        time = provided_values.get('time')

        if target_name == 'time':
            if 'bsp_knots' not in input_names or 'distance' not in input_names: raise ValueError("Missing input for time calc.")
            bsp_ms = knots * METERS_PER_SECOND_PER_KNOT
            if abs(bsp_ms) < TOLERANCE: calculated_value = "Error: Speed=0"
            else: calculated_value = dist / bsp_ms
        elif target_name == 'distance':
            if 'bsp_knots' not in input_names or 'time' not in input_names: raise ValueError("Missing input for distance calc.")
            bsp_ms = knots * METERS_PER_SECOND_PER_KNOT
            calculated_value = bsp_ms * time
        elif target_name == 'bsp_knots':
            if 'distance' not in input_names or 'time' not in input_names: raise ValueError("Missing input for knots calc.")
            if abs(time) < TOLERANCE: calculated_value = "Error: Time=0"
            else:
                 bsp_ms = dist / time
                 calculated_value = bsp_ms * KNOTS_PER_METER_PER_SECOND
        else: calculated_value = "Error: Logic"
    except ZeroDivisionError:
         calculated_value = "Error: Div by 0"
         tkMessageBox.showerror("Math Error", "Shot Calc: Division by zero occurred.")
    except Exception as e:
         calculated_value = "Error: Calc"
         tkMessageBox.showerror("Calculation Error", "Shot Calc: An error occurred: {}".format(e))

    output_var = target_param['in_var']
    display_value = ""
    if calculated_value is not None:
        if isinstance(calculated_value, (int, float)):
            if abs(calculated_value) < TOLERANCE: display_value = ""
            else: display_value = "{:.3f}".format(calculated_value)
        elif isinstance(calculated_value, str): display_value = calculated_value
    output_var.set(display_value)

def calculate_feather():
    checked_items = []
    unchecked_item = None
    for param in feather_params_config:
        if param['chk_var'].get() == 1: checked_items.append(param)
        else: unchecked_item = param

    if len(checked_items) != 3 or unchecked_item is None:
        tkMessageBox.showwarning("Selection Error", "X/I Calc: Please select exactly three parameters as input.")
        return

    provided_values = {}
    try:
        for param in checked_items:
            name = param['name']
            val_str = param['in_var'].get()
            if not val_str:
                 tkMessageBox.showerror("Input Error", "X/I Calc: Selected input field '{}' is empty.".format(param['label']))
                 if unchecked_item: unchecked_item['in_var'].set("")
                 return
            val_float = float(val_str)
            if ('bsp' in name or 'v_across' in name or 'dist' in name) and val_float < 0:
                tkMessageBox.showerror("Input Error", "X/I Calc: Input value for '{}' cannot be negative.".format(param['label']))
                if unchecked_item: unchecked_item['in_var'].set("")
                return
            provided_values[name] = val_float
    except ValueError:
        tkMessageBox.showerror("Input Error", "X/I Calc: Invalid numeric value in one of the selected fields.")
        if unchecked_item: unchecked_item['in_var'].set("")
        return
    except Exception as e:
        tkMessageBox.showerror("Error", "X/I Calc: Error reading inputs: {}".format(e))
        if unchecked_item: unchecked_item['in_var'].set("")
        return

    target_name = unchecked_item['name']
    calculated_value = None
    try:
        Dx = provided_values.get('x_dist')
        Di = provided_values.get('i_dist')
        Vb = provided_values.get('f_bsp')
        Va = provided_values.get('v_across')

        if target_name == 'v_across':
            if Di is None or abs(Di) < TOLERANCE: calculated_value = "Error: Di=0"
            elif Dx is None or Vb is None: raise ValueError("Missing input for Va calc")
            else:
                R = Dx / Di; Vb_sq = Vb * Vb; R_sq = R * R
                Va_sq_denominator = 1.0 + R_sq
                if Va_sq_denominator < TOLERANCE: calculated_value = "Error: Denom=0?"
                else:
                    Va_sq = (R_sq * Vb_sq) / Va_sq_denominator
                    if Va_sq < -TOLERANCE: calculated_value = "Error: Vb/Ratio?"
                    elif Va_sq < 0: calculated_value = 0.0
                    else: calculated_value = math.sqrt(Va_sq)
        elif target_name == 'f_bsp':
            if Va is None: raise ValueError("Missing Va for Vb calc")
            if Dx is None or abs(Dx) < TOLERANCE:
                 if Di is None or abs(Di) < TOLERANCE: calculated_value = abs(Va)
                 else: calculated_value = "Error: Dx=0?"
            elif Di is None: raise ValueError("Missing Di for Vb calc")
            else:
                Di_over_Dx_sq = (Di / Dx)**2
                Vb_sq = Va * Va * (Di_over_Dx_sq + 1.0)
                if Vb_sq < 0: calculated_value = "Error: Speeds?"
                else: calculated_value = math.sqrt(Vb_sq)
        elif target_name == 'x_dist':
            if Va is None or Vb is None or Di is None: raise ValueError("Missing input for Dx calc")
            Vb_sq = Vb * Vb; Va_sq = Va * Va
            if Vb_sq < Va_sq - TOLERANCE : calculated_value = "Error: Vb < Va"
            elif abs(Vb_sq - Va_sq) < TOLERANCE: calculated_value = 0.0
            else:
                Vi_calc = math.sqrt(Vb_sq - Va_sq)
                if abs(Vi_calc) < TOLERANCE: calculated_value = 0.0
                elif abs(Va) < TOLERANCE: calculated_value = 0.0
                else: calculated_value = Di * Va / Vi_calc
        elif target_name == 'i_dist':
            if Va is None or Vb is None or Dx is None: raise ValueError("Missing input for Di calc")
            Vb_sq = Vb * Vb; Va_sq = Va * Va
            if abs(Va) < TOLERANCE:
                 if abs(Dx) < TOLERANCE: calculated_value = 0.0
                 else: calculated_value = "Error: Va=0, Dx!=0"
            elif Vb_sq < Va_sq - TOLERANCE: calculated_value = "Error: Vb < Va"
            elif abs(Vb_sq - Va_sq) < TOLERANCE: calculated_value = 0.0
            else:
                Vi_calc = math.sqrt(Vb_sq - Va_sq)
                calculated_value = Dx * Vi_calc / Va
        else: calculated_value = "Error: Logic"
    except ZeroDivisionError:
        calculated_value = "Error: Div by 0"
        tkMessageBox.showerror("Math Error", "X/I Calc: Division by zero occurred.")
    except ValueError as e:
         calculated_value = "Error: Math/Logic"
         tkMessageBox.showerror("Math Error", "X/I Calc: Math or Logic error: {}".format(e))
    except Exception as e:
         calculated_value = "Error: Calc"
         tkMessageBox.showerror("Calculation Error", "X/I Calc: An error occurred: {}".format(e))

    output_var = unchecked_item['in_var']
    display_value = ""
    if calculated_value is not None:
        if isinstance(calculated_value, (int, float)):
            if abs(calculated_value) < TOLERANCE: display_value = ""
            else: display_value = "{:.3f}".format(calculated_value)
        elif isinstance(calculated_value, str): display_value = calculated_value
    output_var.set(display_value)

def calculate_turn():
    checked_items = []
    unchecked_items = []
    for param in turn_params_config:
        if param['chk_var'].get() == 1: checked_items.append(param)
        else: unchecked_items.append(param)

    if len(checked_items) != 2 or len(unchecked_items) != 1:
        tkMessageBox.showwarning("Selection Error", "Turn Calc: Please select exactly two parameters as input.")
        return

    target_param = unchecked_items[0]
    target_name = target_param['name']
    provided_values = {}
    try:
        for param in checked_items:
            name = param['name']
            val_str = param['in_var'].get()
            if not val_str:
                 tkMessageBox.showerror("Input Error", "Turn Calc: Selected input field '{}' is empty.".format(param['label']))
                 target_param['in_var'].set("")
                 return
            val_float = float(val_str)
            if val_float < 0:
                tkMessageBox.showerror("Input Error", "Turn Calc: Input value for '{}' cannot be negative.".format(param['label']))
                target_param['in_var'].set("")
                return
            provided_values[name] = val_float
    except ValueError:
        tkMessageBox.showerror("Input Error", "Turn Calc: Invalid numeric value in one of the selected fields.")
        target_param['in_var'].set("")
        return
    except Exception as e:
        tkMessageBox.showerror("Error", "Turn Calc: Error reading inputs: {}".format(e))
        target_param['in_var'].set("")
        return

    calculated_value = None
    input_names = set(provided_values.keys())
    try:
        radius_km = provided_values.get('radius_km')
        rate_deg_min = provided_values.get('rate_deg_min')
        bsp_knots = provided_values.get('t_bsp')

        r_m = radius_km * METERS_PER_KM if radius_km is not None else None
        omega_rad_s = rate_deg_min * RADS_PER_DEG / SECS_PER_MIN if rate_deg_min is not None else None
        v_mps = bsp_knots * METERS_PER_SECOND_PER_KNOT if bsp_knots is not None else None

        if target_name == 'radius_km':
            if v_mps is None or omega_rad_s is None: raise ValueError("Missing input for radius calc.")
            if abs(omega_rad_s) < TOLERANCE: calculated_value = "Error: Rate=0"
            else:
                r_m_calc = v_mps / omega_rad_s
                calculated_value = r_m_calc * KM_PER_METER # Use constant
        elif target_name == 'rate_deg_min':
            if v_mps is None or r_m is None: raise ValueError("Missing input for rate calc.")
            if abs(r_m) < TOLERANCE: calculated_value = "Error: Radius=0"
            else:
                omega_rad_s_calc = v_mps / r_m
                calculated_value = omega_rad_s_calc * DEG_PER_RADS * SECS_PER_MIN
        elif target_name == 't_bsp':
            if omega_rad_s is None or r_m is None: raise ValueError("Missing input for BSP calc.")
            v_mps_calc = omega_rad_s * r_m
            calculated_value = v_mps_calc * KNOTS_PER_METER_PER_SECOND
        else: calculated_value = "Error: Logic"
    except ZeroDivisionError:
         calculated_value = "Error: Div by 0"
         tkMessageBox.showerror("Math Error", "Turn Calc: Division by zero occurred.")
    except ValueError as e:
         calculated_value = "Error: Input"
         tkMessageBox.showerror("Error", "Turn Calc: Missing or invalid input combination: {}".format(e))
    except Exception as e:
         calculated_value = "Error: Calc"
         tkMessageBox.showerror("Calculation Error", "Turn Calc: An error occurred: {}".format(e))

    output_var = target_param['in_var']
    display_value = ""
    if calculated_value is not None:
        if isinstance(calculated_value, (int, float)):
            if abs(calculated_value) < TOLERANCE: display_value = ""
            else: display_value = "{:.3f}".format(calculated_value)
        elif isinstance(calculated_value, str): display_value = calculated_value
    output_var.set(display_value)

def calculate_equip_turn():
    """
    Calculates the two unknown equipment turning parameters from three knowns.
    """
    checked_items = []
    unchecked_items = []
    for param in equip_turn_params_config:
        if param['chk_var'].get() == 1: checked_items.append(param)
        else: unchecked_items.append(param)

    if len(checked_items) != 3 or len(unchecked_items) != 2:
        tkMessageBox.showwarning("Selection Error", "Equip Turn Calc: Please select exactly three parameters as input.")
        return

    provided_values = {}
    try:
        for param in checked_items:
            name = param['name']
            val_str = param['in_var'].get()
            if not val_str:
                 tkMessageBox.showerror("Input Error", "Equip Turn Calc: Selected input field '{}' is empty.".format(param['label']))
                 for p in unchecked_items: p['in_var'].set("")
                 return
            val_float = float(val_str)
            if val_float < 0:
                tkMessageBox.showerror("Input Error", "Equip Turn Calc: Input value for '{}' cannot be negative.".format(param['label']))
                for p in unchecked_items: p['in_var'].set("")
                return
            provided_values[name] = val_float
    except ValueError:
        tkMessageBox.showerror("Input Error", "Equip Turn Calc: Invalid numeric value in one of the selected fields.")
        for p in unchecked_items: p['in_var'].set("")
        return
    except Exception as e:
        tkMessageBox.showerror("Error", "Equip Turn Calc: Error reading inputs: {}".format(e))
        for p in unchecked_items: p['in_var'].set("")
        return

    target_names = {p['name'] for p in unchecked_items}
    calculated_values = {}
    try:
        Rv = provided_values.get('vessel_radius')
        Vv = provided_values.get('vessel_speed')
        W  = provided_values.get('equip_width')
        Vo = provided_values.get('outer_speed')
        Vi = provided_values.get('inner_speed')

        if 'outer_speed' in target_names and 'inner_speed' in target_names:
            if Rv <= W / 2.0: raise ValueError("Vessel radius must be > half equipment width.")
            if abs(Rv) < TOLERANCE: raise ZeroDivisionError("Vessel Radius cannot be zero.")
            calculated_values['outer_speed'] = Vv * (Rv + W / 2.0) / Rv
            calculated_values['inner_speed'] = Vv * (Rv - W / 2.0) / Rv

        elif 'equip_width' in target_names and 'inner_speed' in target_names:
            if abs(Vv) < TOLERANCE: raise ZeroDivisionError("Vessel Speed cannot be zero.")
            W_calc = 2.0 * Rv * (Vo / Vv - 1.0)
            if W_calc < -TOLERANCE: raise ValueError("Inconsistent speeds (Vessel > Outer).")
            calculated_values['equip_width'] = W_calc if W_calc > 0 else 0.0
            if Rv <= W_calc / 2.0: raise ValueError("Calculated width is too large for the turn radius.")
            calculated_values['inner_speed'] = Vv * (Rv - W_calc / 2.0) / Rv

        elif 'equip_width' in target_names and 'outer_speed' in target_names:
            if abs(Vv) < TOLERANCE: raise ZeroDivisionError("Vessel Speed cannot be zero.")
            W_calc = 2.0 * Rv * (1.0 - Vi / Vv)
            if W_calc < -TOLERANCE: raise ValueError("Inconsistent speeds (Inner > Vessel).")
            calculated_values['equip_width'] = W_calc if W_calc > 0 else 0.0
            calculated_values['outer_speed'] = Vv * (Rv + W_calc / 2.0) / Rv
        
        elif 'vessel_speed' in target_names and 'inner_speed' in target_names:
            if Rv <= W / 2.0: raise ValueError("Vessel radius must be > half equipment width.")
            denominator = Rv + W / 2.0
            if abs(denominator) < TOLERANCE: raise ZeroDivisionError("Outer radius cannot be zero.")
            Vv_calc = Vo * Rv / denominator
            calculated_values['vessel_speed'] = Vv_calc
            calculated_values['inner_speed'] = Vv_calc * (Rv - W / 2.0) / Rv

        elif 'vessel_speed' in target_names and 'outer_speed' in target_names:
            denominator = Rv - W / 2.0
            if abs(denominator) < TOLERANCE: raise ZeroDivisionError("Inner radius cannot be zero.")
            if Rv < W / 2.0: raise ValueError("Vessel radius must be >= half equipment width.")
            Vv_calc = Vi * Rv / denominator
            if Vv_calc < -TOLERANCE: raise ValueError("Calculated vessel speed is negative.")
            calculated_values['vessel_speed'] = Vv_calc if Vv_calc > 0 else 0.0
            calculated_values['outer_speed'] = Vv_calc * (Rv + W / 2.0) / Rv

        elif 'vessel_radius' in target_names and 'inner_speed' in target_names:
            denominator = Vo - Vv
            if abs(denominator) < TOLERANCE: raise ZeroDivisionError("Outer and Vessel speeds cannot be equal.")
            Rv_calc = (Vv * W / 2.0) / denominator
            if Rv_calc < -TOLERANCE: raise ValueError("Inconsistent speeds (Vessel > Outer).")
            calculated_values['vessel_radius'] = Rv_calc if Rv_calc > 0 else 0.0
            if Rv_calc <= W / 2.0: raise ValueError("Calculated radius is too small for equipment width.")
            calculated_values['inner_speed'] = Vv * (Rv_calc - W / 2.0) / Rv_calc

        elif 'vessel_radius' in target_names and 'outer_speed' in target_names:
            denominator = Vv - Vi
            if abs(denominator) < TOLERANCE: raise ZeroDivisionError("Vessel and Inner speeds cannot be equal.")
            Rv_calc = (Vv * W / 2.0) / denominator
            if Rv_calc < -TOLERANCE: raise ValueError("Inconsistent speeds (Inner > Vessel).")
            calculated_values['vessel_radius'] = Rv_calc if Rv_calc > 0 else 0.0
            if Rv_calc <= W / 2.0: raise ValueError("Calculated radius is too small for equipment width.")
            calculated_values['outer_speed'] = Vv * (Rv_calc + W / 2.0) / Rv_calc

        elif 'vessel_speed' in target_names and 'equip_width' in target_names:
            denominator = Vo + Vi
            if abs(denominator) < TOLERANCE: raise ZeroDivisionError("Sum of inner and outer speeds is zero.")
            W_calc = 2.0 * Rv * (Vo - Vi) / denominator
            if W_calc < -TOLERANCE: raise ValueError("Inconsistent speeds (Inner > Outer).")
            calculated_values['equip_width'] = W_calc if W_calc > 0 else 0.0
            calculated_values['vessel_speed'] = (Vo + Vi) / 2.0
            
        elif 'vessel_radius' in target_names and 'vessel_speed' in target_names:
            denominator = Vo - Vi
            if abs(denominator) < TOLERANCE: raise ZeroDivisionError("Inner and Outer speeds cannot be equal.")
            Rv_calc = (W / 2.0) * (Vo + Vi) / denominator
            if Rv_calc < -TOLERANCE: raise ValueError("Inconsistent speeds (Inner > Outer).")
            calculated_values['vessel_radius'] = Rv_calc if Rv_calc > 0 else 0.0
            calculated_values['vessel_speed'] = (Vo + Vi) / 2.0

        elif 'vessel_radius' in target_names and 'equip_width' in target_names:
            if abs((Vo + Vi) - 2.0 * Vv) > TOLERANCE * 2.0:
                raise ValueError("Inputs are inconsistent. Vessel speed must be the average of Inner and Outer speeds.")
            else:
                raise ValueError("This combination of inputs is not sufficient to determine a unique Radius and Width.")
        else:
             raise NotImplementedError("This calculation case has not been implemented.")

    except (ZeroDivisionError, ValueError, NotImplementedError) as e:
         tkMessageBox.showerror("Calculation Error", "Equip Turn Calc: {}".format(e))
         for out_param in unchecked_items: out_param['in_var'].set("")
         return
    except Exception as e:
         tkMessageBox.showerror("Calculation Error", "Equip Turn Calc: An unexpected error occurred: {}".format(e))
         for out_param in unchecked_items: out_param['in_var'].set("")
         return

    for output_param in unchecked_items:
        output_name = output_param['name']
        output_var = output_param['in_var']
        if output_name in calculated_values:
            result = calculated_values[output_name]
            display_value = ""
            if isinstance(result, (int, float)):
                if abs(result) < TOLERANCE: display_value = ""
                else: display_value = "{:.3f}".format(result)
            elif isinstance(result, str): display_value = result
            output_var.set(display_value)
        else:
            output_var.set("")

def calculate_bsp_conv():
    checked_item = None
    unchecked_items = []
    for param in bsp_conv_params_config:
        if param['chk_var'].get() == 1: checked_item = param
        else: unchecked_items.append(param)

    if checked_item is None or len(unchecked_items) != 2:
        tkMessageBox.showwarning("Selection Error", "BSP Conv: Please select exactly one parameter as input.")
        return

    input_param = checked_item
    input_name = input_param['name']
    try:
        val_str = input_param['in_var'].get()
        if not val_str:
             tkMessageBox.showerror("Input Error", "BSP Conv: Selected input field '{}' is empty.".format(input_param['label']))
             for out_param in unchecked_items: out_param['in_var'].set("")
             return
        input_value = float(val_str)
        if input_value < 0:
             tkMessageBox.showerror("Input Error", "BSP Conv: Speed cannot be negative.")
             for out_param in unchecked_items: out_param['in_var'].set("")
             return
    except ValueError:
        tkMessageBox.showerror("Input Error", "BSP Conv: Invalid numeric value entered.")
        for out_param in unchecked_items: out_param['in_var'].set("")
        return
    except Exception as e:
        tkMessageBox.showerror("Error", "BSP Conv: Error reading input: {}".format(e))
        for out_param in unchecked_items: out_param['in_var'].set("")
        return

    calculated_results = {}
    try:
        mps_value = 0.0
        if input_name == 'bsp_knots_conv': mps_value = input_value * METERS_PER_SECOND_PER_KNOT
        elif input_name == 'bsp_ms_conv': mps_value = input_value
        elif input_name == 'bsp_kmh_conv': mps_value = input_value * MPS_PER_KMH
        else: raise ValueError("Unknown input unit")

        for output_param in unchecked_items:
            output_name = output_param['name']
            if output_name == 'bsp_knots_conv': calculated_results[output_name] = mps_value * KNOTS_PER_METER_PER_SECOND
            elif output_name == 'bsp_ms_conv': calculated_results[output_name] = mps_value
            elif output_name == 'bsp_kmh_conv': calculated_results[output_name] = mps_value * KMH_PER_MPS
    except Exception as e:
         tkMessageBox.showerror("Calculation Error", "BSP Conv: An error occurred during conversion: {}".format(e))
         for out_param in unchecked_items: out_param['in_var'].set("")
         return

    for output_param in unchecked_items:
        output_name = output_param['name']
        output_var = output_param['in_var']
        if output_name in calculated_results:
            result = calculated_results[output_name]
            display_value = ""
            if isinstance(result, (int, float)):
                if abs(result) < TOLERANCE: display_value = ""
                else: display_value = "{:.3f}".format(result)
            elif isinstance(result, str): display_value = result
            output_var.set(display_value)
        else:
            output_var.set("")

def calculate_dist_conv():
    checked_item = None
    unchecked_items = []
    for param in dist_conv_params_config:
        if param['chk_var'].get() == 1: checked_item = param
        else: unchecked_items.append(param)

    if checked_item is None or len(unchecked_items) != 3:
        tkMessageBox.showwarning("Selection Error", "Dist Conv: Please select exactly one parameter as input.")
        return

    input_param = checked_item
    input_name = input_param['name']
    try:
        val_str = input_param['in_var'].get()
        if not val_str:
             tkMessageBox.showerror("Input Error", "Dist Conv: Selected input field '{}' is empty.".format(input_param['label']))
             for out_param in unchecked_items: out_param['in_var'].set("")
             return
        input_value = float(val_str)
        if input_value < 0:
             tkMessageBox.showerror("Input Error", "Dist Conv: Distance cannot be negative.")
             for out_param in unchecked_items: out_param['in_var'].set("")
             return

    except ValueError:
        tkMessageBox.showerror("Input Error", "Dist Conv: Invalid numeric value entered.")
        for out_param in unchecked_items: out_param['in_var'].set("")
        return
    except Exception as e:
        tkMessageBox.showerror("Error", "Dist Conv: Error reading input: {}".format(e))
        for out_param in unchecked_items: out_param['in_var'].set("")
        return

    calculated_results = {}
    try:
        m_value = 0.0
        if input_name == 'dist_m': m_value = input_value
        elif input_name == 'dist_nm': m_value = input_value * METERS_PER_NM
        elif input_name == 'dist_km': m_value = input_value * METERS_PER_KM
        elif input_name == 'dist_mi': m_value = input_value * METERS_PER_MI
        else: raise ValueError("Unknown input unit")

        for output_param in unchecked_items:
            output_name = output_param['name']
            if output_name == 'dist_m': calculated_results[output_name] = m_value
            elif output_name == 'dist_nm': calculated_results[output_name] = m_value * NM_PER_METER
            elif output_name == 'dist_km': calculated_results[output_name] = m_value * KM_PER_METER
            elif output_name == 'dist_mi': calculated_results[output_name] = m_value * MI_PER_METER

    except Exception as e:
         tkMessageBox.showerror("Calculation Error", "Dist Conv: An error occurred during conversion: {}".format(e))
         for out_param in unchecked_items: out_param['in_var'].set("")
         return

    for output_param in unchecked_items:
        output_name = output_param['name']
        output_var = output_param['in_var']
        if output_name in calculated_results:
            result = calculated_results[output_name]
            display_value = ""
            if isinstance(result, (int, float)):
                if abs(result) < TOLERANCE: display_value = ""
                else: display_value = "{:.3f}".format(result)
            elif isinstance(result, str): display_value = result
            output_var.set(display_value)
        else:
            output_var.set("")


# --- GUI Helper Function ---
def create_calculator_frame(parent, config_list, calc_type, title, instructions, button_text, command):
    """
    Creates and packs a standardized calculator frame into the parent widget.
    """
    frame = tk.Frame(parent, bd=2, relief=tk.GROOVE, padx=10, pady=10, bg=NIPPON_BLUE_AURA)
    frame.pack(pady=(5, 10), padx=10, fill=tk.X)

    # Headers and Instructions
    tk.Label(frame, text=title, font=("Arial", 10, "bold"), bg=NIPPON_BLUE_AURA).grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=5, pady=(0, 5))
    tk.Label(frame, text=instructions, font=("Arial", 9), bg=NIPPON_BLUE_AURA).grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=5, pady=(0, 15))

    # Create Widgets Dynamically
    current_row = 2
    for param_config in config_list:
        param_config['chk_var'] = tk.IntVar(value=0)
        param_config['in_var'] = tk.StringVar()
        chk = tk.Checkbutton(frame, variable=param_config['chk_var'], command=lambda t=calc_type: update_checkbox_states(t), bg=NIPPON_BLUE_AURA, activebackground=NIPPON_BLUE_AURA)
        param_config['chk_widget'] = chk
        lbl = tk.Label(frame, text=param_config['label'], bg=NIPPON_BLUE_AURA)
        entry = tk.Entry(frame, textvariable=param_config['in_var'], width=18, readonlybackground=READONLY_BG, foreground='black')
        param_config['entry_widget'] = entry
        chk.grid(row=current_row, column=0, sticky=tk.W, padx=(0, 5))
        lbl.grid(row=current_row, column=1, sticky=tk.W, padx=5)
        entry.grid(row=current_row, column=2, sticky=tk.EW, pady=3)
        current_row += 1

    # Calculate Button
    tk.Button(frame, text=button_text, command=command, bg=BUTTON_BG_COLOR, fg=BUTTON_FG, activebackground=BUTTON_BG_COLOR).grid(row=current_row, column=1, columnspan=2, pady=(15, 0), sticky=tk.E)

    # Configure grid weights
    frame.grid_columnconfigure(1, weight=0)
    frame.grid_columnconfigure(2, weight=1)


class SeisCalPanel(tk.Frame):
    """
    Scrollable calculator UI for xSeisCal.
    Parent is a tk.Tk (standalone) or the xNAVSL tab host / EmbedHost (embedded).
    """

    def __init__(self, master, **kw):
        kw.setdefault("bg", NIPPON_BLUE_AURA)
        tk.Frame.__init__(self, master, **kw)
        self._standalone_root = isinstance(master, tk.Tk)

        self.main_frame = tk.Frame(self, bg=NIPPON_BLUE_AURA)
        self.main_frame.pack(fill=tk.BOTH, expand=1)

        self.my_canvas = tk.Canvas(self.main_frame, bg=NIPPON_BLUE_AURA)
        self.my_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=1)

        self.my_scrollbar = tk.Scrollbar(self.main_frame, orient=tk.VERTICAL, command=self.my_canvas.yview)
        self.my_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.my_canvas.configure(yscrollcommand=self.my_scrollbar.set)

        self.scrollable_frame = tk.Frame(self.my_canvas, bg=NIPPON_BLUE_AURA)
        self._canvas_inner_id = self.my_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.scrollable_frame.bind("<Configure>", self._seiscal_set_scrollregion)
        self.my_canvas.bind("<Configure>", self._seiscal_on_canvas_configure)
        self.main_frame.bind("<Map>", self._seiscal_on_main_map)

        tk.Label(
            self.scrollable_frame,
            text="xSeisCal: Useful Calculations for Navigators",
            font=("Arial", 12, "bold"),
            pady=10,
            bg=NIPPON_BLUE_AURA,
        ).pack(fill=tk.X)

        create_calculator_frame(
            self.scrollable_frame,
            shot_params_config,
            "shot",
            "Shot Distance/Time/Speed Calculator",
            "Tick exactly 2 boxes, enter values, then click Calculate",
            "Calculate Shot",
            calculate_shot,
        )
        create_calculator_frame(
            self.scrollable_frame,
            feather_params_config,
            "feather",
            "Xline/Inline Calculator",
            "Tick exactly 3 boxes, enter values, then click Calculate",
            "Calculate X/I",
            calculate_feather,
        )
        create_calculator_frame(
            self.scrollable_frame,
            turn_params_config,
            "turn",
            "Turn Rate/Radius Calculator",
            "Tick exactly 2 boxes, enter values, then click Calculate",
            "Calculate Turn",
            calculate_turn,
        )
        create_calculator_frame(
            self.scrollable_frame,
            equip_turn_params_config,
            "equip_turn",
            "Equipment Turn Water Speed Calculator",
            "Tick exactly 3 boxes, enter values, then click Calculate",
            "Calculate Equip. WSP",
            calculate_equip_turn,
        )
        create_calculator_frame(
            self.scrollable_frame,
            bsp_conv_params_config,
            "bsp_conv",
            "BSP Converter",
            "Tick exactly 1 box, enter value, then click Convert",
            "Convert BSP",
            calculate_bsp_conv,
        )
        create_calculator_frame(
            self.scrollable_frame,
            dist_conv_params_config,
            "dist_conv",
            "Distance Converter",
            "Tick exactly 1 box, enter value, then click Convert",
            "Convert Distance",
            calculate_dist_conv,
        )

        update_checkbox_states("shot")
        update_checkbox_states("feather")
        update_checkbox_states("turn")
        update_checkbox_states("equip_turn")
        update_checkbox_states("bsp_conv")
        update_checkbox_states("dist_conv")

        if self._standalone_root:
            self.my_canvas.bind("<MouseWheel>", self._seiscal_on_mousewheel)
            self.my_canvas.bind("<Button-4>", self._seiscal_on_mousewheel_linux_up)
            self.my_canvas.bind("<Button-5>", self._seiscal_on_mousewheel_linux_down)
            self._seiscal_bind_mousewheel_recursive(self.scrollable_frame)
        else:
            self._seiscal_setup_embedded_notebook_wheel()

        self._seiscal_set_scrollregion()
        if not self._standalone_root:
            self.after(100, self._seiscal_set_scrollregion)

    def _is_under_main_frame(self, widget):
        """True if widget is main_frame or a descendant (for embedded notebook routing)."""
        w = widget
        while w:
            if w is self.main_frame:
                return True
            try:
                w = w.master
            except Exception:
                break
        return False

    def _seiscal_set_scrollregion(self, _event=None):
        try:
            self.my_canvas.update_idletasks()
            bbox = self.my_canvas.bbox("all")
            if bbox:
                self.my_canvas.configure(scrollregion=bbox)
        except tk.TclError:
            pass

    def _seiscal_on_canvas_configure(self, event):
        try:
            w = getattr(event, "width", 0) or 0
            if w <= 1:
                return
            self.my_canvas.itemconfig(self._canvas_inner_id, width=w)
        except tk.TclError:
            pass
        self._seiscal_set_scrollregion()

    def _seiscal_on_main_map(self, _event=None):
        try:
            self.after(10, self._seiscal_set_scrollregion)
            self.after(200, self._seiscal_set_scrollregion)
        except Exception:
            pass

    def _seiscal_on_mousewheel(self, event):
        try:
            if event.delta:
                self.my_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except (tk.TclError, AttributeError):
            pass
        return "break"

    def _seiscal_on_mousewheel_linux_up(self, event):
        try:
            self.my_canvas.yview_scroll(-1, "units")
        except tk.TclError:
            pass
        return "break"

    def _seiscal_on_mousewheel_linux_down(self, event):
        try:
            self.my_canvas.yview_scroll(1, "units")
        except tk.TclError:
            pass
        return "break"

    def _seiscal_bind_mousewheel_recursive(self, widget):
        try:
            widget.bind("<MouseWheel>", self._seiscal_on_mousewheel)
            widget.bind("<Button-4>", self._seiscal_on_mousewheel_linux_up)
            widget.bind("<Button-5>", self._seiscal_on_mousewheel_linux_down)
        except tk.TclError:
            pass
        for ch in widget.winfo_children():
            self._seiscal_bind_mousewheel_recursive(ch)

    def _seiscal_setup_embedded_notebook_wheel(self):
        """
        When embedded in xNAVSL, per-widget MouseWheel binding is unreliable after other tabs
        steal or reorder events. Use bind_all with pointer/ancestor checks.
        """
        panel = self

        def _widget_for_wheel(event):
            w = event.widget
            if panel._is_under_main_frame(w):
                return w
            try:
                w = panel.winfo_containing(event.x_root, event.y_root)
            except Exception:
                return None
            if w and panel._is_under_main_frame(w):
                return w
            return None

        def _dispatch_wheel(event):
            if _widget_for_wheel(event) is None:
                return
            try:
                if hasattr(event, "delta") and event.delta:
                    panel.my_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except (tk.TclError, AttributeError):
                pass
            return "break"

        def _dispatch_linux_up(event):
            if _widget_for_wheel(event) is None:
                return
            try:
                panel.my_canvas.yview_scroll(-1, "units")
            except tk.TclError:
                pass
            return "break"

        def _dispatch_linux_down(event):
            if _widget_for_wheel(event) is None:
                return
            try:
                panel.my_canvas.yview_scroll(1, "units")
            except tk.TclError:
                pass
            return "break"

        try:
            top = self.winfo_toplevel()
            top.bind_all("<MouseWheel>", _dispatch_wheel, add="+")
            top.bind_all("<Button-4>", _dispatch_linux_up, add="+")
            top.bind_all("<Button-5>", _dispatch_linux_down, add="+")
        except Exception:
            pass

        try:
            self.my_canvas.bind("<Enter>", lambda e: self.my_canvas.focus_set())
        except Exception:
            pass


class SeisCalApp(tk.Tk):
    """Standalone top-level window (same as running this script directly)."""

    def __init__(self):
        tk.Tk.__init__(self)
        self.title("xSeisCal")
        self.geometry("500x1300")
        panel = SeisCalPanel(self)
        panel.pack(fill=tk.BOTH, expand=True)


def xnavsl_embed(master):
    """Option C: xNAVSL loads this module and calls this to place the UI inside the tab."""
    panel = SeisCalPanel(master)
    panel.pack(fill=tk.BOTH, expand=True)
    return panel


if __name__ == "__main__":
    app = SeisCalApp()
    app.mainloop()
