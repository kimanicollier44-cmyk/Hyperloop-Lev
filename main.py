#!/usr/bin/env python3
"""Hyperloop-Lev - evacuated tube levitation transport lab.

by Darion Kellar

Pure Python standard library. Zero dependencies. Zero network.
Simulation only: the evolution of MagLevX - the same EDS levitation
physics moved from an open guideway into a low-pressure tube.
Tube aerodynamics (ideal-gas density, Kantrowitz choking limit,
compressor bypass), EDS levitation carried over from MagLevX,
linear-motor propulsion to a 1,200 km/h DESIGN TARGET (a labelled
target, not a claim), an LA -> San Francisco trip simulation,
tube pressure systems and leak safety math, emergency braking,
near-vacuum thermal rejection, a TinyML kNN regime classifier,
Gemini Carbon 4 as DECIDER (names-only, tighten-only), Muse as
advisor (never overrides HOLD), and Google Flow plan-only seats.

Every live-operation / real-hardware action is a permanent HOLD gate.
"""
import hashlib
import json
import math
import sys

# ---------------------------------------------------------------- constants
G = 9.80665                         # standard gravity, m/s^2
R_GAS = 287.05                      # specific gas constant of air, J/(kg*K)
GAMMA = 1.4                         # heat capacity ratio of air
T_TUBE_K = 293.15                   # tube air temperature (lab model), K
P_ATM_PA = 101325.0                 # sea-level atmosphere, Pa
P_TUBE_PA = 100.0                   # design tube pressure (lab model), Pa
SIGMA = 5.670374419e-8              # Stefan-Boltzmann constant, W/(m^2 K^4)

VERSION = "1.0.0"

# Reference pod + tube (lab model, concept-class numbers, SIM ONLY)
POD = {
    "mass_kg": 15000.0,
    "length_m": 25.0,
    "diameter_m": 2.4,
    "cd": 0.20,                     # drag coefficient (labelled model value)
    "seats": 28,
    "bogies": 4,
    "aux_power_kw": 20.0,           # labelled auxiliary load
    "propulsion_efficiency": 0.90,
    "regen_share": 0.65,            # braking energy recovered (as MagLevX)
}
TUBE = {
    "diameter_m": 4.0,
    "section_km": 25.0,             # bulkhead-isolated section length (model)
}

POD_AREA_M2 = math.pi * (POD["diameter_m"] / 2.0) ** 2      # 4.5239 m^2
TUBE_AREA_M2 = math.pi * (TUBE["diameter_m"] / 2.0) ** 2    # 12.5664 m^2
BLOCKAGE = POD_AREA_M2 / TUBE_AREA_M2                       # 0.36 exactly

DESIGN_CRUISE_KMH = 1200.0          # DESIGN TARGET - labelled, not a claim
ROUTE_LA_SF_M = 560000.0            # LA -> San Francisco, ~560 km

# ---------------------------------------------------------------- HOLD gates
HOLD_GATES = {
    "live_passenger_operation": "HOLD - no live passenger operation, ever; nobody rides a simulation",
    "real_hardware_control": "HOLD - no control of real pods, pumps, motors, or tube hardware",
    "bypass_pressure_interlocks": "HOLD - pressure interlocks and bulkhead isolation are never bypassed",
    "disable_emergency_venting": "HOLD - emergency venting / repressurisation paths are never disabled",
    "claim_certified_system": "HOLD - no claim this simulation is a certified transport system",
    "commercial_service_claim": "HOLD - no commercial service claims from a lab model",
    "vacuum_operation_live": "HOLD - no live vacuum / low-pressure tube operation directed from a sim",
    "exceed_test_limits_live": "HOLD - test-envelope limits are never exceeded on live hardware",
    "remove_human_override": "HOLD - the human override is never removed",
    "cargo_hazmat_live": "HOLD - no live hazmat cargo planning on a passenger pod model",
    "medical_claim": "HOLD - no medical transport or life-support claims beyond labelled sim math",
    "investment_claim": "HOLD - no investment claims; a lab model is not a prospectus",
    "construction_claim": "HOLD - no construction guidance for real tubes, tunnels, or pylons",
    "regulatory_approval_claim": "HOLD - no claim of regulatory approval or pending certification",
}


def gate(action):
    """Return 'HOLD' if the action is gated, else 'PROCEED' (sandbox sim)."""
    return "HOLD" if action in HOLD_GATES else "PROCEED"


def kmh_to_mps(kmh):
    return kmh / 3.6


def mps_to_kmh(mps):
    return mps * 3.6


# ================================================================ 1. Tube aero
# Air in the tube is an ideal gas: rho = P / (R * T). Dropping the
# pressure from 101,325 Pa to ~100 Pa drops the density - and with it
# the aerodynamic drag - by the same factor of ~1,013. That is the
# entire reason the tube exists.
def air_density(pressure_pa, temp_k=T_TUBE_K):
    """Ideal-gas density of air: rho = P / (R_specific * T)."""
    if pressure_pa <= 0 or temp_k <= 0:
        raise ValueError("pressure and temperature must be positive")
    return pressure_pa / (R_GAS * temp_k)


def speed_of_sound(temp_k=T_TUBE_K):
    """a = sqrt(gamma * R * T) - independent of pressure for an ideal gas."""
    return math.sqrt(GAMMA * R_GAS * temp_k)


def aero_drag_force(speed_mps, pressure_pa=P_TUBE_PA):
    """Aerodynamic drag in the tube: F = 0.5 * rho * Cd * A * v^2."""
    rho = air_density(pressure_pa)
    return 0.5 * rho * POD["cd"] * POD_AREA_M2 * speed_mps ** 2


def aero_drag_power_kw(speed_mps, pressure_pa=P_TUBE_PA):
    """Power burned pushing air aside: P = F * v, in kW."""
    return aero_drag_force(speed_mps, pressure_pa) * speed_mps / 1000.0


# Kantrowitz limit: air ahead of the pod must squeeze through the
# annulus between pod and tube wall. If the pod goes too fast the
# annulus flow chokes (reaches Mach 1) and drag explodes. The limit
# Mach number solves the isentropic area-Mach relation
#   A/A*(M) = 1 / (1 - blockage)
# where A/A*(M) = (1/M) * [ (2/(gamma+1)) * (1 + (gamma-1)/2 M^2) ]
#                        ^ ((gamma+1) / (2 (gamma-1)))
def area_mach_ratio(mach):
    """Isentropic A/A* for a Mach number in (0, 1]. A/A*(1) = 1."""
    if not 0.0 < mach <= 1.0:
        raise ValueError("mach must be in (0, 1]")
    base = (2.0 / (GAMMA + 1.0)) * (1.0 + (GAMMA - 1.0) / 2.0 * mach ** 2)
    exponent = (GAMMA + 1.0) / (2.0 * (GAMMA - 1.0))
    return (1.0 / mach) * base ** exponent


def kantrowitz_mach(blockage=BLOCKAGE):
    """Mach at which the annulus chokes for this blockage (bisection)."""
    if not 0.0 < blockage < 1.0:
        raise ValueError("blockage must be in (0, 1)")
    target = 1.0 / (1.0 - blockage)
    lo, hi = 1e-6, 1.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if area_mach_ratio(mid) > target:
            lo = mid        # A/A* falls as M rises toward 1 on this branch
        else:
            hi = mid
    return round(0.5 * (lo + hi), 4)


def kantrowitz_speed_mps(blockage=BLOCKAGE):
    """Kantrowitz speed limit in m/s at tube temperature."""
    return kantrowitz_mach(blockage) * speed_of_sound()


# Compressor bypass (concept model, LABELLED): above the Kantrowitz
# speed the pod carries a nose compressor that swallows the air it
# runs into and ejects it behind the pod, relaxing the choking
# limit. Mass flow = rho * v * A_pod; shaft power from the isentropic
# compression work at a labelled pressure ratio and efficiency.
BYPASS_PRESSURE_RATIO = 1.2         # labelled model value
BYPASS_EFFICIENCY = 0.70            # labelled model value


def bypass_mass_flow(speed_mps, pressure_pa=P_TUBE_PA):
    """Air mass the nose compressor must swallow: mdot = rho * v * A."""
    return air_density(pressure_pa) * speed_mps * POD_AREA_M2


def bypass_power_kw(speed_mps, pressure_pa=P_TUBE_PA):
    """Compressor shaft power (kW) - isentropic work per kg times mdot."""
    mdot = bypass_mass_flow(speed_mps, pressure_pa)
    work_per_kg = ((GAMMA / (GAMMA - 1.0)) * R_GAS * T_TUBE_K
                   * (BYPASS_PRESSURE_RATIO ** ((GAMMA - 1.0) / GAMMA) - 1.0)
                   / BYPASS_EFFICIENCY)
    return mdot * work_per_kg / 1000.0


def aero_report():
    v = kmh_to_mps(DESIGN_CRUISE_KMH)
    rho_tube = air_density(P_TUBE_PA)
    rho_atm = air_density(P_ATM_PA)
    mk = kantrowitz_mach()
    return {
        "design_cruise_kmh": DESIGN_CRUISE_KMH,
        "design_cruise_mach": round(v / speed_of_sound(), 4),
        "rho_at_100pa_kg_m3": round(rho_tube, 6),
        "rho_at_1atm_kg_m3": round(rho_atm, 4),
        "density_ratio_atm_over_tube": round(rho_atm / rho_tube, 2),
        "drag_at_cruise_100pa_n": round(aero_drag_force(v), 1),
        "drag_at_cruise_1atm_n": round(aero_drag_force(v, P_ATM_PA), 1),
        "drag_power_at_cruise_100pa_kw": round(aero_drag_power_kw(v), 2),
        "drag_power_at_cruise_1atm_kw": round(aero_drag_power_kw(v, P_ATM_PA), 1),
        "blockage_ratio": round(BLOCKAGE, 4),
        "kantrowitz_mach": mk,
        "kantrowitz_speed_kmh": round(mps_to_kmh(kantrowitz_speed_mps()), 1),
        "bypass_required_at_cruise": v > kantrowitz_speed_mps(),
        "bypass_mass_flow_kg_s": round(bypass_mass_flow(v), 3),
        "bypass_power_kw": round(bypass_power_kw(v), 1),
        "note": "at 1 atm the same pod at 1,200 km/h would need ~1,013x the "
                "drag power - the tube is a drag-delete, paid for with pumps; "
                "above the Kantrowitz speed a bypass compressor (labelled "
                "concept model) must swallow the bow air",
        "gate": gate("vacuum_operation_live"),
    }


# ================================================================ 2. Levitation
# EDS levitation carried over from MagLevX: same force law, same
# constants (K_EDS, V0, reference gap, magnetic-drag shape), scaled
# by bogie count - the pod carries 4 bogies where the MagLevX
# trainset carries 16, so K and the drag peak scale by 4/16.
#   F_lift = K * (1 - exp(-v / V0)) * (GAP_REF / gap)
# Force is zero at standstill: the pod rests on skids/wheels below
# liftoff speed, exactly as in MagLevX.
EDS_K_TRAINSET = 6.5e6     # N - MagLevX trainset constant, stated for reuse
EDS_V0 = 40.0              # m/s speed scale (MagLevX)
EDS_GAP_REF = 0.10         # m reference gap (MagLevX)
EDS_DRAG_PEAK_TRAINSET_N = 18000.0   # N (MagLevX)
EDS_DRAG_VPEAK = 30.0      # m/s (MagLevX)
BOGIE_SCALE = POD["bogies"] / 16.0   # 4 pod bogies vs 16 trainset bogies
EDS_K = EDS_K_TRAINSET * BOGIE_SCALE
EDS_DRAG_PEAK_N = EDS_DRAG_PEAK_TRAINSET_N * BOGIE_SCALE
LEV_BASE_KW = 5.0          # labelled excitation / cryo base draw


def eds_lift(speed_mps, gap_m=EDS_GAP_REF):
    """Total repulsive EDS lift of the pod in newtons (MagLevX law)."""
    if gap_m <= 0:
        raise ValueError("gap must be positive")
    if speed_mps < 0:
        raise ValueError("speed must be >= 0")
    return EDS_K * (1.0 - math.exp(-speed_mps / EDS_V0)) * (EDS_GAP_REF / gap_m)


def eds_liftoff_speed(mass_kg=POD["mass_kg"], gap_m=EDS_GAP_REF):
    """Speed where EDS lift first equals pod weight (bisection)."""
    target = mass_kg * G
    lo, hi = 0.0, 400.0
    if eds_lift(hi, gap_m) < target:
        return -1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if eds_lift(mid, gap_m) < target:
            lo = mid
        else:
            hi = mid
    return round(0.5 * (lo + hi), 4)


def eds_magnetic_drag(speed_mps):
    """Magnetic drag (N): peak * (v/vp) * exp(1 - v/vp) - MagLevX shape."""
    if speed_mps < 0:
        raise ValueError("speed must be >= 0")
    if speed_mps == 0:
        return 0.0
    x = speed_mps / EDS_DRAG_VPEAK
    return EDS_DRAG_PEAK_N * x * math.exp(1.0 - x)


def levitation_power_kw(speed_mps):
    """Levitation draw: magnetic-drag work plus labelled base draw."""
    return eds_magnetic_drag(speed_mps) * speed_mps / 1000.0 + LEV_BASE_KW


def levitation_report():
    v = kmh_to_mps(DESIGN_CRUISE_KMH)
    v_lo = eds_liftoff_speed()
    return {
        "source": "MagLevX EDS law and constants, scaled by bogies 4/16",
        "eds_k_trainset_n": EDS_K_TRAINSET,
        "eds_k_pod_n": EDS_K,
        "pod_weight_n": round(POD["mass_kg"] * G, 1),
        "lift_at_standstill_n": 0.0,
        "liftoff_speed_mps": v_lo,
        "liftoff_speed_kmh": round(mps_to_kmh(v_lo), 1),
        "wheels_or_skids_below_liftoff": True,
        "magnetic_drag_peak_n": EDS_DRAG_PEAK_N,
        "levitation_power_at_30mps_kw": round(levitation_power_kw(30.0), 1),
        "levitation_power_at_cruise_kw": round(levitation_power_kw(v), 2),
        "note": "levitation drag power peaks at low speed (~30 m/s) and "
                "falls away at cruise - the EDS tax is paid early, "
                "exactly as MagLevX modelled it at train scale",
        "gate": gate("real_hardware_control"),
    }


# ================================================================ 3. Propulsion
# Linear motor along the tube. Service acceleration is capped by a
# passenger-comfort limit enforced in the model: the requested accel
# is clamped, and the profile sim records its peak g so the checks
# can prove the limit held.
A_MAX = 0.8            # m/s^2 service acceleration (comfort-capped, model)
JERK_MAX = 0.5         # m/s^3 ride-comfort jerk limit (as MagLevX)
G_LIMIT = 0.10         # g - hard comfort ceiling used by the checks


def accel_time_to_speed(speed_mps, accel=A_MAX):
    """Constant-acceleration time from rest: t = v / a."""
    return speed_mps / accel


def accel_distance(speed_mps, accel=A_MAX):
    """Constant-acceleration distance from rest: d = v^2 / (2a)."""
    return speed_mps ** 2 / (2.0 * accel)


def comfort_clamp(accel_mps2):
    """Enforce the comfort limit: requested accel is capped at A_MAX."""
    return max(-A_MAX, min(A_MAX, accel_mps2))


def thrust_for_accel(mass_kg, accel, speed_mps):
    """Motor thrust (N) = m*a + tube aero drag + EDS magnetic drag."""
    return (mass_kg * accel + aero_drag_force(speed_mps)
            + eds_magnetic_drag(speed_mps))


def pod_power_kw(speed_mps, accel_mps2):
    """Total pod power draw (kW) at a speed / acceleration state.

    Propulsion: thrust*v / efficiency when driving; braking energy
    is recovered at the regen share when the motor force is negative.
    Plus levitation, bypass compressor (only above the Kantrowitz
    speed, where the bow air must be swallowed), and auxiliaries.
    """
    thrust = thrust_for_accel(POD["mass_kg"], accel_mps2, speed_mps)
    mech_kw = thrust * speed_mps / 1000.0
    if mech_kw >= 0:
        prop_kw = mech_kw / POD["propulsion_efficiency"]
    else:
        prop_kw = mech_kw * POD["regen_share"]
    comp_kw = (bypass_power_kw(speed_mps)
               if speed_mps > kantrowitz_speed_mps() else 0.0)
    return prop_kw + levitation_power_kw(speed_mps) + comp_kw + POD["aux_power_kw"]


def trip_profile(distance_m=ROUTE_LA_SF_M, vmax_mps=None, a_max=A_MAX,
                 jerk=JERK_MAX, dt=0.1):
    """Jerk-limited trapezoidal run with energy integration (sim).

    Accelerate (accel ramps at the jerk limit, comfort-clamped) ->
    cruise -> brake to stop exactly at the destination. Energy is
    integrated from pod_power_kw at every step. Deterministic.
    """
    if vmax_mps is None:
        vmax_mps = kmh_to_mps(DESIGN_CRUISE_KMH)
    v, a, x, t = 0.0, 0.0, 0.0, 0.0
    top, peak_a, energy_kwh = 0.0, 0.0, 0.0
    while True:
        stop_dist = v * v / (2.0 * a_max) + v * (a_max / jerk) * 0.5
        remaining = distance_m - x
        if remaining <= 0.01 and v <= 0.05:
            break
        if stop_dist >= remaining:
            target_a = -a_max
        elif v < vmax_mps:
            target_a = a_max
        else:
            target_a = 0.0
        da = target_a - a
        max_da = jerk * dt
        a += max(-max_da, min(max_da, da))
        a = comfort_clamp(a)
        v = max(0.0, v + a * dt)
        if v > vmax_mps:
            v = vmax_mps
        energy_kwh += pod_power_kw(v, a) * dt / 3600.0
        x += v * dt
        t += dt
        top = max(top, v)
        peak_a = max(peak_a, abs(a))
        if t > 20000:  # safety bound, never reached on sane inputs
            break
    seats = POD["seats"]
    return {
        "distance_m": round(x, 1),
        "route_m": distance_m,
        "travel_time_s": round(t, 1),
        "travel_time_min": round(t / 60.0, 2),
        "top_speed_mps": round(top, 3),
        "top_speed_kmh": round(mps_to_kmh(top), 1),
        "peak_accel_mps2": round(peak_a, 3),
        "peak_g": round(peak_a / G, 4),
        "trip_energy_kwh": round(energy_kwh, 1),
        "energy_per_passenger_km": round(energy_kwh / (distance_m / 1000.0 * seats), 4),
        "a_max_mps2": a_max,
        "jerk_max_mps3": jerk,
    }


def trip_phases(distance_m=ROUTE_LA_SF_M, vmax_mps=None, a_max=A_MAX):
    """Analytic accel / cruise / decel phase split (constant-accel)."""
    if vmax_mps is None:
        vmax_mps = kmh_to_mps(DESIGN_CRUISE_KMH)
    d_acc = accel_distance(vmax_mps, a_max)
    if 2.0 * d_acc >= distance_m:
        # triangular profile: never reaches cruise speed
        v_peak = math.sqrt(a_max * distance_m)
        t_half = v_peak / a_max
        return {
            "profile": "triangular (route too short for cruise speed)",
            "peak_speed_kmh": round(mps_to_kmh(v_peak), 1),
            "accel_time_s": round(t_half, 1),
            "cruise_time_s": 0.0,
            "decel_time_s": round(t_half, 1),
            "total_time_s": round(2.0 * t_half, 1),
            "total_time_min": round(2.0 * t_half / 60.0, 2),
        }
    d_cruise = distance_m - 2.0 * d_acc
    t_acc = accel_time_to_speed(vmax_mps, a_max)
    t_cruise = d_cruise / vmax_mps
    return {
        "profile": "trapezoidal",
        "peak_speed_kmh": round(mps_to_kmh(vmax_mps), 1),
        "accel_distance_km": round(d_acc / 1000.0, 2),
        "accel_time_s": round(t_acc, 1),
        "cruise_distance_km": round(d_cruise / 1000.0, 2),
        "cruise_time_s": round(t_cruise, 1),
        "decel_time_s": round(t_acc, 1),
        "total_time_s": round(2.0 * t_acc + t_cruise, 1),
        "total_time_min": round((2.0 * t_acc + t_cruise) / 60.0, 2),
    }


# Reference figures - LABELED ESTIMATES for comparison only, not measured.
ENERGY_REFERENCE = {
    "hyperloop_lev_model": None,  # filled from the trip sim in the report fn
    "maglevx_model_430kmh": 0.0281,   # MagLevX lab model output, labelled
    "high_speed_rail_est": 0.035,
    "short_haul_air_est": 0.18,
    "note": "ESTIMATES for classroom comparison - not measured data",
}

FLIGHT_LA_SF_BLOCK_MIN = 85.0   # labelled estimate: flight block time alone


def energy_comparison():
    prof = trip_profile()
    out = dict(ENERGY_REFERENCE)
    out["hyperloop_lev_model"] = prof["energy_per_passenger_km"]
    out["trip_time_min_sim"] = prof["travel_time_min"]
    out["flight_block_time_min_est"] = FLIGHT_LA_SF_BLOCK_MIN
    out["units"] = "kWh per passenger-km"
    return out


# ================================================================ 4. Pressure
# The tube is not one long vacuum: bulkhead doors split it into
# isolated sections (25 km model sections). Pumps hold the design
# pressure against a labelled leak/outgassing load; if a breach
# repressurises one section, only that section fills - and the pod's
# breathing reserve is sized against that timeline.
LEAK_LOAD_PA_M3_S = 2000.0     # labelled route leak/outgassing load
PUMP_EFFICIENCY = 0.60         # labelled
SECTION_COUNT = math.ceil(ROUTE_LA_SF_M / (TUBE["section_km"] * 1000.0))


def tube_air_mass_kg(distance_m=ROUTE_LA_SF_M, pressure_pa=P_TUBE_PA):
    """Mass of air in a tube stretch: rho * A_tube * L."""
    return air_density(pressure_pa) * TUBE_AREA_M2 * distance_m


def pump_power_kw(pressure_pa=P_TUBE_PA, leak_load=LEAK_LOAD_PA_M3_S):
    """Pump power to hold pressure: Q * ln(P_atm / P_tube) / eta."""
    if pressure_pa <= 0 or pressure_pa >= P_ATM_PA:
        raise ValueError("tube pressure must be in (0, P_atm)")
    return leak_load * math.log(P_ATM_PA / pressure_pa) / PUMP_EFFICIENCY / 1000.0


def section_volume_m3(section_km=TUBE["section_km"]):
    return TUBE_AREA_M2 * section_km * 1000.0


# Breach inflow: choked (sonic) orifice flow from atmosphere into
# the near-vacuum section - mdot stays at the choked value while the
# section pressure is below ~0.528 * P_atm.
BREACH_AREA_M2 = 0.01          # labelled breach size, m^2
BREACH_CD = 0.80               # labelled discharge coefficient


def choked_mass_flow_kg_s(area_m2=BREACH_AREA_M2, cd=BREACH_CD,
                          p_upstream=P_ATM_PA):
    """Choked orifice mass flow: Cd*A*P0*sqrt(gamma/(R*T))*flow factor."""
    flow_factor = (1.0 + (GAMMA - 1.0) / 2.0) ** (-(GAMMA + 1.0) / (2.0 * (GAMMA - 1.0)))
    return cd * area_m2 * p_upstream * math.sqrt(GAMMA / (R_GAS * T_TUBE_K)) * flow_factor


def repressurise_time_s(target_pa=10000.0, section_km=TUBE["section_km"]):
    """Time for one breached section to fill from P_TUBE to target_pa.

    Choked inflow is constant over this range, so t = dm / mdot.
    Safety math only (sim) - emergency venting is a HOLD gate live.
    """
    dm = (air_density(target_pa) - air_density(P_TUBE_PA)) * section_volume_m3(section_km)
    return dm / choked_mass_flow_kg_s()


# Pod emergency breathing reserve (labelled sim model): stored O2
# against per-passenger consumption. The reserve must outlast the
# worst labelled rescue timeline - the section repressurisation.
O2_RESERVE_KG = 25.0           # labelled stored oxygen
O2_USE_KG_PER_PAX_HOUR = 0.035  # labelled consumption rate


def breathing_reserve_hours(passengers=POD["seats"], reserve_kg=O2_RESERVE_KG):
    """Endurance of the pod breathing reserve: reserve / (pax * rate)."""
    return reserve_kg / (passengers * O2_USE_KG_PER_PAX_HOUR)


def pressure_report():
    t_fill = repressurise_time_s()
    reserve_h = breathing_reserve_hours()
    return {
        "design_pressure_pa": P_TUBE_PA,
        "route_air_mass_at_design_kg": round(tube_air_mass_kg(), 1),
        "route_air_mass_at_1atm_kg": round(tube_air_mass_kg(pressure_pa=P_ATM_PA), 1),
        "pump_power_kw_labelled": round(pump_power_kw(), 2),
        "sections_on_route": SECTION_COUNT,
        "section_length_km": TUBE["section_km"],
        "section_volume_m3": round(section_volume_m3(), 1),
        "breach_area_m2_labelled": BREACH_AREA_M2,
        "breach_inflow_kg_s": round(choked_mass_flow_kg_s(), 3),
        "section_repressurise_to_10kpa_h": round(t_fill / 3600.0, 2),
        "breathing_reserve_h": round(reserve_h, 2),
        "reserve_margin_x": round(reserve_h / (t_fill / 3600.0), 2),
        "note": "one breached section fills alone (bulkheads isolate it); "
                "the pod breathing reserve outlasts that fill time by the "
                "margin shown - safety math in sim only",
        "gate": gate("bypass_pressure_interlocks"),
    }


# ================================================================ 5. Braking
SERVICE_DECEL = 0.8    # m/s^2 (matches the comfort-capped accel)
EDDY_DECEL = 1.0       # m/s^2 labelled eddy-current emergency brake
SKID_DECEL = 0.3       # m/s^2 labelled friction-skid backup (levitation lost)
REACTION_S = 10.0      # s signalling / reaction margin (model)


def braking_distance(speed_mps, decel):
    """Stopping distance at constant decel: d = v^2 / (2 * decel)."""
    return speed_mps ** 2 / (2.0 * decel)


def braking_energy_kwh(speed_mps, mass_kg=POD["mass_kg"]):
    """Kinetic energy at speed: 0.5 m v^2, in kWh."""
    return 0.5 * mass_kg * speed_mps ** 2 / 3.6e6


def block_spacing(speed_mps):
    """Minimum pod spacing: eddy stop + reaction margin + pod length."""
    dist = (braking_distance(speed_mps, EDDY_DECEL)
            + speed_mps * REACTION_S + POD["length_m"])
    return {
        "speed_kmh": round(mps_to_kmh(speed_mps), 1),
        "block_spacing_m": round(dist, 1),
        "block_spacing_km": round(dist / 1000.0, 2),
        "headway_time_s": round(dist / speed_mps, 1) if speed_mps > 0 else -1.0,
        "eddy_stop_m": round(braking_distance(speed_mps, EDDY_DECEL), 1),
    }


def line_capacity(speed_mps):
    """Pods per hour per direction at minimum block spacing."""
    b = block_spacing(speed_mps)
    if b["headway_time_s"] <= 0:
        return -1.0
    return round(3600.0 / b["headway_time_s"], 1)


def braking_report(speed_mps=None):
    if speed_mps is None:
        speed_mps = kmh_to_mps(DESIGN_CRUISE_KMH)
    e = braking_energy_kwh(speed_mps)
    b = block_spacing(speed_mps)
    return {
        "from_kmh": round(mps_to_kmh(speed_mps), 1),
        "service_decel_mps2": SERVICE_DECEL,
        "service_distance_m": round(braking_distance(speed_mps, SERVICE_DECEL), 1),
        "eddy_decel_mps2": EDDY_DECEL,
        "eddy_distance_m": round(braking_distance(speed_mps, EDDY_DECEL), 1),
        "skid_decel_mps2": SKID_DECEL,
        "skid_distance_m": round(braking_distance(speed_mps, SKID_DECEL), 1),
        "kinetic_energy_kwh": round(e, 1),
        "regen_share": POD["regen_share"],
        "recovered_kwh": round(e * POD["regen_share"], 1),
        "eddy_heat_kwh": round(e * (1.0 - POD["regen_share"]), 1),
        "block_spacing_km": b["block_spacing_km"],
        "pods_per_hour_per_direction": line_capacity(speed_mps),
        "split_note": "service braking is regenerative first; the eddy "
                      "brake is the emergency layer and the friction skid "
                      "is the last resort if levitation is lost",
        "gate": gate("disable_emergency_venting"),
    }


# ================================================================ 6. Thermal
# At ~100 Pa there is almost no air to carry heat away: convection
# is gone for practical purposes. The pod rejects heat the way a
# spacecraft does - radiation (Stefan-Boltzmann) plus a phase-change
# buffer for peaks. Labelled model throughout.
HEAT_LOADS_KW = {
    "passengers_28_at_100w": 2.8,
    "avionics_and_controls_labelled": 5.0,
    "compressor_waste_heat_share_labelled": 2.2,
}
RADIATOR_EMISSIVITY = 0.9      # labelled
RADIATOR_TEMP_K = 320.0        # labelled radiator skin temperature
TUBE_WALL_TEMP_K = 293.15      # labelled sink temperature
PCM_LATENT_KJ_KG = 200.0       # labelled phase-change buffer


def total_heat_load_kw():
    return round(sum(HEAT_LOADS_KW.values()), 4)


def radiator_flux_w_m2(radiator_k=RADIATOR_TEMP_K, sink_k=TUBE_WALL_TEMP_K,
                       emissivity=RADIATOR_EMISSIVITY):
    """Net radiated flux: eps * sigma * (T_rad^4 - T_sink^4)."""
    return emissivity * SIGMA * (radiator_k ** 4 - sink_k ** 4)


def radiator_area_m2(load_kw=None, radiator_k=RADIATOR_TEMP_K,
                     sink_k=TUBE_WALL_TEMP_K):
    """Radiator area needed to reject the load: A = P / flux."""
    if load_kw is None:
        load_kw = total_heat_load_kw()
    return load_kw * 1000.0 / radiator_flux_w_m2(radiator_k, sink_k)


def pod_skin_area_m2():
    """Lateral skin area of the pod cylinder: pi * d * L."""
    return math.pi * POD["diameter_m"] * POD["length_m"]


def pcm_buffer_mass_kg(load_kw=None, minutes=30.0):
    """Phase-change mass to absorb the load with no radiator: E / L."""
    if load_kw is None:
        load_kw = total_heat_load_kw()
    energy_kj = load_kw * minutes * 60.0
    return energy_kj / PCM_LATENT_KJ_KG


def thermal_report():
    load = total_heat_load_kw()
    area = radiator_area_m2(load)
    skin = pod_skin_area_m2()
    return {
        "heat_loads_kw": HEAT_LOADS_KW,
        "total_heat_load_kw": load,
        "convection_note": "at ~100 Pa convective cooling is negligible - "
                           "radiation and stored buffer do all the work",
        "radiator_flux_w_m2": round(radiator_flux_w_m2(), 1),
        "radiator_area_needed_m2": round(area, 1),
        "pod_skin_area_m2": round(skin, 1),
        "skin_fraction_needed": round(area / skin, 3),
        "pcm_buffer_30min_kg": round(pcm_buffer_mass_kg(load, 30.0), 1),
        "gate": gate("exceed_test_limits_live"),
    }


# ================================================================ 7. kNN classifier
# Features: (distance / 100 km, log10 tube pressure Pa, blockage * 10)
# -> regime label. A design point is feasible only if the route is a
# sane tube length, the pressure is deep enough to delete the drag,
# and the blockage leaves the annulus (or the bypass) room to work.
_KNN_TRAIN = [
    ((5.6, 2.0, 3.6), "feasible"), ((5.0, 2.0, 3.4), "feasible"),
    ((6.2, 2.1, 3.8), "feasible"), ((3.0, 1.9, 3.2), "feasible"),
    ((4.5, 2.2, 3.5), "feasible"), ((7.5, 2.0, 3.7), "feasible"),
    ((5.6, 3.3, 3.6), "marginal"), ((6.5, 3.2, 3.9), "marginal"),
    ((4.5, 3.0, 4.0), "marginal"), ((3.5, 2.6, 4.8), "marginal"),
    ((5.0, 2.2, 5.2), "marginal"), ((13.0, 2.1, 3.6), "marginal"),
    ((12.0, 2.3, 3.8), "marginal"), ((10.0, 2.2, 3.9), "marginal"),
    ((40.0, 2.0, 3.6), "infeasible"), ((38.0, 2.5, 4.0), "infeasible"),
    ((35.0, 2.2, 3.3), "infeasible"), ((5.6, 5.0, 3.6), "infeasible"),
    ((4.0, 4.8, 4.5), "infeasible"), ((6.2, 4.7, 3.9), "infeasible"),
    ((5.6, 2.0, 6.5), "infeasible"), ((6.0, 2.3, 6.2), "infeasible"),
    ((4.5, 2.1, 6.0), "infeasible"),
]


def design_features(distance_km, pressure_pa, blockage):
    """Map a design point into classifier feature space."""
    return (distance_km / 100.0, math.log10(pressure_pa), blockage * 10.0)


class RegimeClassifier:
    """kNN (k=3) over (distance, pressure, blockage) features."""

    def __init__(self, k=3):
        self.k = k
        self.train = list(_KNN_TRAIN)

    @staticmethod
    def _dist(a, b):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    def classify(self, features):
        ranked = sorted(self.train, key=lambda t: self._dist(features, t[0]))
        votes = {}
        for _, label in ranked[: self.k]:
            votes[label] = votes.get(label, 0) + 1
        return sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def training_accuracy(self):
        hits = sum(1 for f, label in self.train if self.classify(f) == label)
        return round(hits / len(self.train), 4)


SCENARIOS = {
    "la_sf_design": (560.0, 100.0, 0.36),
    "regional_300km_500pa": (300.0, 500.0, 0.42),
    "cross_country_open_air": (4000.0, 101325.0, 0.36),
    "fat_pod_small_tube": (560.0, 100.0, 0.65),
}


def regime_report():
    clf = RegimeClassifier()
    return {
        "training_accuracy": clf.training_accuracy(),
        "scenarios": {name: clf.classify(design_features(*point))
                      for name, point in SCENARIOS.items()},
    }


# ================================================================ 8. Advisory seats
def _trace(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def carbon4_decide(topic="hyperloop-lev-demo"):
    """Gemini Carbon 4 DECIDER seat: MAP->MODEL->STRESS->DECIDE.

    Names-only keys, live calls 0, tighten-only: can add HOLDs, never lift one.
    """
    stages = ["MAP", "MODEL", "STRESS", "DECIDE"]
    payload = {"seat": "gemini-carbon-4", "topic": topic, "stages": stages}
    return {
        "seat": "Gemini Carbon 4 Extended Thinking",
        "role": "DECIDER",
        "pipeline": stages,
        "tiers": [2048, 8192, 32768],
        "key": "names-only (GEMINI_API_KEY name checked, value never read)",
        "live_calls": 0,
        "can_override_hold": False,
        "tighten_only": True,
        "decision": "PROCEED (sandbox simulation only)",
        "trace_sha256_16": _trace(payload),
    }


def claude_advisor(topic="hyperloop-lev-demo"):
    """Muse advisor seat: advisory only, authority none."""
    return {
        "seat": "Muse",
        "role": "advisor",
        "authority": "none - advisory only",
        "can_override_hold": False,
        "live_calls": 0,
        "advice": "Keep every live tube operation behind its HOLD gate.",
        "trace_sha256_16": _trace({"seat": "claude-advisor", "topic": topic}),
    }


def google_flow_plan():
    """Google Flow: plan-only. Nothing renders, nothing is sent."""
    return {
        "seat": "Google Flow",
        "flows": ["FlowX task graph", "Workspace Studio drafts",
                  "Filmmaking 5-shot storyboard", "DataX data-flow"],
        "rendered": False,
        "live": 0,
        "plan": ["pod in the tube hero shot", "Kantrowitz choking explainer",
                 "LA to SF trip timeline", "section isolation safety story"],
    }


def brains_report():
    return {"decider": carbon4_decide(), "advisor": claude_advisor(),
            "flow": google_flow_plan()}


# ================================================================ checks
def run_checks():
    c = []

    def chk(name, ok):
        c.append((name, bool(ok)))

    v = kmh_to_mps(DESIGN_CRUISE_KMH)
    # --- tube aerodynamics
    chk("kmh_mps_roundtrip", abs(mps_to_kmh(kmh_to_mps(1200.0)) - 1200.0) < 1e-9)
    chk("density_atm_plausible", 1.19 < air_density(P_ATM_PA) < 1.22)
    chk("density_scales_with_pressure",
        abs(air_density(P_ATM_PA) / air_density(P_TUBE_PA)
            - P_ATM_PA / P_TUBE_PA) < 1e-6)
    chk("sound_speed_pressure_independent",
        abs(speed_of_sound() - math.sqrt(GAMMA * R_GAS * T_TUBE_K)) < 1e-9)
    chk("drag_ratio_equals_density_ratio",
        abs(aero_drag_force(v, P_ATM_PA) / aero_drag_force(v, P_TUBE_PA)
            - P_ATM_PA / P_TUBE_PA) < 1e-4)
    chk("drag_quadruples_when_speed_doubles",
        abs(aero_drag_force(100.0) / aero_drag_force(50.0) - 4.0) < 1e-9)
    chk("drag_power_1atm_over_1000x_tube",
        aero_drag_power_kw(v, P_ATM_PA) / aero_drag_power_kw(v, P_TUBE_PA) > 1000.0)
    chk("blockage_is_036", abs(BLOCKAGE - 0.36) < 1e-12)
    chk("area_mach_at_mach1_is_1", abs(area_mach_ratio(1.0) - 1.0) < 1e-12)
    mk = kantrowitz_mach()
    chk("kantrowitz_solves_area_relation",
        abs(area_mach_ratio(mk) - 1.0 / (1.0 - BLOCKAGE)) < 0.01)
    chk("kantrowitz_falls_with_blockage",
        kantrowitz_mach(0.20) > mk > kantrowitz_mach(0.50))
    chk("cruise_is_supersonic_vs_kantrowitz", v > kantrowitz_speed_mps())
    chk("bypass_required_at_cruise", aero_report()["bypass_required_at_cruise"] is True)
    chk("bypass_mass_flow_formula",
        abs(bypass_mass_flow(v) - air_density(P_TUBE_PA) * v * POD_AREA_M2) < 1e-9)
    chk("bypass_power_positive_at_cruise", bypass_power_kw(v) > 0)
    # --- levitation (MagLevX carry-over)
    chk("eds_zero_at_standstill", eds_lift(0.0) == 0.0)
    chk("eds_k_scaled_by_bogies", abs(EDS_K - EDS_K_TRAINSET * 0.25) < 1e-6)
    v_lo = eds_liftoff_speed()
    chk("eds_liftoff_exists", v_lo > 0)
    chk("eds_liftoff_balances_weight",
        abs(eds_lift(v_lo) - POD["mass_kg"] * G) < 50.0)
    chk("eds_drag_zero_at_rest", eds_magnetic_drag(0.0) == 0.0)
    chk("eds_drag_peaks_at_vpeak",
        abs(eds_magnetic_drag(EDS_DRAG_VPEAK) - EDS_DRAG_PEAK_N) < 1e-6)
    chk("eds_drag_falls_after_peak", eds_magnetic_drag(v) < EDS_DRAG_PEAK_N)
    chk("levitation_power_peaks_early",
        levitation_power_kw(30.0) > levitation_power_kw(v))
    # --- propulsion + trip
    chk("accel_time_formula", abs(accel_time_to_speed(v) - v / A_MAX) < 1e-12)
    chk("accel_distance_formula",
        abs(accel_distance(v) - v ** 2 / (2.0 * A_MAX)) < 1e-9)
    chk("comfort_clamp_caps", comfort_clamp(2.5) == A_MAX
        and comfort_clamp(-2.5) == -A_MAX and comfort_clamp(0.3) == 0.3)
    chk("comfort_ceiling_below_tenth_g", A_MAX / G < G_LIMIT)
    chk("thrust_exceeds_drag_at_cruise_accel",
        thrust_for_accel(POD["mass_kg"], A_MAX, v)
        > aero_drag_force(v) + eds_magnetic_drag(v))
    prof = trip_profile()
    chk("profile_reaches_design_cruise", abs(prof["top_speed_kmh"] - 1200.0) < 1.0)
    chk("profile_covers_route", abs(prof["distance_m"] - ROUTE_LA_SF_M) < 500.0)
    chk("profile_time_plausible", 1700.0 < prof["travel_time_s"] < 2600.0)
    chk("profile_peak_g_within_comfort", prof["peak_g"] <= G_LIMIT)
    chk("trip_energy_positive", prof["trip_energy_kwh"] > 0)
    ec = energy_comparison()
    chk("energy_per_pax_km_positive", ec["hyperloop_lev_model"] > 0)
    chk("energy_model_below_air_estimate",
        ec["hyperloop_lev_model"] < ec["short_haul_air_est"])
    chk("trip_faster_than_flight_block", prof["travel_time_min"] < FLIGHT_LA_SF_BLOCK_MIN)
    phases = trip_phases()
    chk("phases_trapezoidal_on_route", phases["profile"] == "trapezoidal")
    short = trip_phases(distance_m=50000.0)
    chk("phases_triangular_on_short_route",
        short["profile"].startswith("triangular")
        and abs(short["peak_speed_kmh"] - mps_to_kmh(math.sqrt(A_MAX * 50000.0))) < 0.2)
    # --- pressure systems
    chk("tube_air_mass_formula",
        abs(tube_air_mass_kg() - air_density(P_TUBE_PA) * TUBE_AREA_M2 * ROUTE_LA_SF_M) < 1e-6)
    chk("tube_air_mass_ratio", abs(tube_air_mass_kg(pressure_pa=P_ATM_PA)
                                   / tube_air_mass_kg() - P_ATM_PA / P_TUBE_PA) < 1e-4)
    chk("pump_power_formula",
        abs(pump_power_kw() - LEAK_LOAD_PA_M3_S * math.log(P_ATM_PA / P_TUBE_PA)
            / PUMP_EFFICIENCY / 1000.0) < 1e-9)
    chk("pump_power_rises_as_pressure_drops", pump_power_kw(50.0) > pump_power_kw(100.0))
    chk("section_count_covers_route", SECTION_COUNT * TUBE["section_km"] * 1000.0 >= ROUTE_LA_SF_M)
    chk("choked_flow_formula",
        abs(choked_mass_flow_kg_s()
            - BREACH_CD * BREACH_AREA_M2 * P_ATM_PA
            * math.sqrt(GAMMA / (R_GAS * T_TUBE_K)) * (1.2) ** -3.0) < 1e-9)
    chk("repressurise_time_positive", repressurise_time_s() > 0)
    chk("breathing_reserve_formula",
        abs(breathing_reserve_hours() - O2_RESERVE_KG
            / (POD["seats"] * O2_USE_KG_PER_PAX_HOUR)) < 1e-9)
    chk("reserve_outlasts_repressurisation",
        pressure_report()["reserve_margin_x"] > 1.0)
    chk("pressure_gate_hold", pressure_report()["gate"] == "HOLD")
    # --- braking + spacing
    chk("braking_service_formula",
        abs(braking_distance(v, SERVICE_DECEL) - v ** 2 / (2 * SERVICE_DECEL)) < 1e-9)
    chk("braking_eddy_shorter_than_service",
        braking_distance(v, EDDY_DECEL) < braking_distance(v, SERVICE_DECEL))
    chk("braking_skid_longest",
        braking_distance(v, SKID_DECEL) > braking_distance(v, SERVICE_DECEL))
    br = braking_report()
    chk("braking_split_sums", abs(br["recovered_kwh"] + br["eddy_heat_kwh"]
                                  - br["kinetic_energy_kwh"]) < 0.2)
    chk("block_spacing_exceeds_eddy_stop",
        block_spacing(v)["block_spacing_m"] > braking_distance(v, EDDY_DECEL))
    chk("capacity_positive", line_capacity(v) > 0)
    chk("braking_gate_hold", br["gate"] == "HOLD")
    # --- thermal
    chk("radiator_flux_zero_at_equal_temps",
        radiator_flux_w_m2(300.0, 300.0) == 0.0)
    chk("radiator_flux_positive", radiator_flux_w_m2() > 0)
    chk("radiator_area_formula",
        abs(radiator_area_m2(10.0) - 10000.0 / radiator_flux_w_m2()) < 1e-9)
    chk("radiator_fits_pod_skin", radiator_area_m2() < pod_skin_area_m2())
    chk("pcm_buffer_formula",
        abs(pcm_buffer_mass_kg(10.0, 30.0) - 10.0 * 30.0 * 60.0 / PCM_LATENT_KJ_KG) < 1e-9)
    chk("heat_load_is_sum", abs(total_heat_load_kw() - 10.0) < 1e-9)
    # --- classifier
    rr = regime_report()
    chk("classifier_accuracy", rr["training_accuracy"] >= 0.85)
    chk("classifier_design_feasible", rr["scenarios"]["la_sf_design"] == "feasible")
    chk("classifier_regional_marginal",
        rr["scenarios"]["regional_300km_500pa"] == "marginal")
    chk("classifier_open_air_infeasible",
        rr["scenarios"]["cross_country_open_air"] == "infeasible")
    chk("classifier_fat_pod_infeasible",
        rr["scenarios"]["fat_pod_small_tube"] == "infeasible")
    # --- gates + seats
    chk("hold_gates_14", len(HOLD_GATES) == 14
        and all(v.startswith("HOLD") for v in HOLD_GATES.values()))
    chk("gate_passenger_hold", gate("live_passenger_operation") == "HOLD")
    chk("gate_sandbox_proceed", gate("run_simulation") == "PROCEED")
    b = brains_report()
    chk("carbon4_no_override", b["decider"]["can_override_hold"] is False)
    chk("claude_no_override", b["advisor"]["can_override_hold"] is False)
    chk("flow_plan_only", b["flow"]["rendered"] is False and b["flow"]["live"] == 0)
    return c


# ================================================================ CLI / demo
def demo():
    print("=" * 68)
    print("Hyperloop-Lev - evacuated tube levitation transport lab")
    print("by Darion Kellar | MIT | pure stdlib | zero network | SIM ONLY")
    print("=" * 68)
    v = kmh_to_mps(DESIGN_CRUISE_KMH)
    print("\n[1] Tube aerodynamics: why the tube exists")
    ar = aero_report()
    print(f"    air density: {ar['rho_at_1atm_kg_m3']} kg/m^3 at 1 atm -> "
          f"{ar['rho_at_100pa_kg_m3']} kg/m^3 at 100 Pa (x{ar['density_ratio_atm_over_tube']})")
    print(f"    drag at 1,200 km/h (DESIGN TARGET): {ar['drag_at_cruise_100pa_n']} N in the tube "
          f"vs {ar['drag_at_cruise_1atm_n']:,.0f} N in open air")
    print(f"    drag power: {ar['drag_power_at_cruise_100pa_kw']} kW vs "
          f"{ar['drag_power_at_cruise_1atm_kw']:,.0f} kW - the tube deletes the drag")
    print(f"    blockage {ar['blockage_ratio']} -> Kantrowitz limit Mach {ar['kantrowitz_mach']} "
          f"= {ar['kantrowitz_speed_kmh']} km/h; cruise Mach {ar['design_cruise_mach']} needs the bypass")
    print(f"    bypass compressor (labelled model): swallows {ar['bypass_mass_flow_kg_s']} kg/s, "
          f"{ar['bypass_power_kw']} kW")
    print("\n[2] Levitation: EDS carried over from MagLevX (bogies 4/16)")
    lr = levitation_report()
    print(f"    lift at standstill = 0 N (skids until liftoff at {lr['liftoff_speed_kmh']} km/h)")
    print(f"    levitation power: {lr['levitation_power_at_30mps_kw']} kW at 30 m/s "
          f"-> {lr['levitation_power_at_cruise_kw']} kW at cruise (drag tax paid early)")
    print("\n[3] Trip sim: Los Angeles -> San Francisco, 560 km")
    prof = trip_profile()
    ph = trip_phases()
    print(f"    phases (analytic): accel {ph['accel_distance_km']} km / {ph['accel_time_s']} s, "
          f"cruise {ph['cruise_distance_km']} km / {ph['cruise_time_s']} s, decel {ph['decel_time_s']} s")
    print(f"    sim: {prof['travel_time_min']} min station to station, top speed "
          f"{prof['top_speed_kmh']} km/h, peak {prof['peak_g']} g (comfort cap {G_LIMIT} g)")
    print(f"    flight block time alone is ~{FLIGHT_LA_SF_BLOCK_MIN:.0f} min (labelled estimate)")
    print("\n[4] Energy")
    ec = energy_comparison()
    print(f"    trip energy = {prof['trip_energy_kwh']} kWh -> {ec['hyperloop_lev_model']} "
          f"kWh/passenger-km (model)")
    print(f"    references (ESTIMATES): MagLevX model {ec['maglevx_model_430kmh']}, "
          f"HSR {ec['high_speed_rail_est']}, air {ec['short_haul_air_est']}")
    print("\n[5] Pressure systems + leak safety (sim math)")
    pr = pressure_report()
    print(f"    air in the whole 560 km tube at 100 Pa: {pr['route_air_mass_at_design_kg']:,.0f} kg "
          f"(vs {pr['route_air_mass_at_1atm_kg']:,.0f} kg at 1 atm)")
    print(f"    pumps hold pressure for {pr['pump_power_kw_labelled']} kW (labelled leak load); "
          f"{pr['sections_on_route']} bulkhead sections of {pr['section_length_km']} km")
    print(f"    breach in one section: fills to 10 kPa in {pr['section_repressurise_to_10kpa_h']} h; "
          f"pod breathing reserve {pr['breathing_reserve_h']} h -> margin x{pr['reserve_margin_x']}")
    print("\n[6] Emergency braking from 1,200 km/h")
    br = braking_report()
    print(f"    service ({SERVICE_DECEL} m/s^2): {br['service_distance_m']:,.0f} m | "
          f"eddy ({EDDY_DECEL} m/s^2): {br['eddy_distance_m']:,.0f} m | "
          f"skid ({SKID_DECEL} m/s^2): {br['skid_distance_m']:,.0f} m")
    print(f"    kinetic energy {br['kinetic_energy_kwh']} kWh -> regen {br['recovered_kwh']} kWh, "
          f"eddy heat {br['eddy_heat_kwh']} kWh")
    print(f"    block spacing {br['block_spacing_km']} km -> "
          f"{br['pods_per_hour_per_direction']} pods/hour/direction")
    print("\n[7] Thermal: no air, no convection")
    tr = thermal_report()
    print(f"    heat load {tr['total_heat_load_kw']} kW; radiator at {RADIATOR_TEMP_K} K radiates "
          f"{tr['radiator_flux_w_m2']} W/m^2 -> {tr['radiator_area_needed_m2']} m^2 of the "
          f"{tr['pod_skin_area_m2']} m^2 skin")
    print(f"    phase-change buffer for 30 min with no radiator: {tr['pcm_buffer_30min_kg']} kg")
    print("\n[8] Regime classifier (TinyML kNN)")
    rep = regime_report()
    print(f"    training accuracy = {rep['training_accuracy']}")
    for name, label in rep["scenarios"].items():
        print(f"    {name:24s} -> {label}")
    print("\n[9] Advisory seats")
    print(f"    decider: {carbon4_decide()['decision']} trace={carbon4_decide()['trace_sha256_16']}")
    print(f"    advisor can_override_hold = {claude_advisor()['can_override_hold']}")
    print(f"    flow rendered = {google_flow_plan()['rendered']} live = {google_flow_plan()['live']}")
    print(f"\n[10] HOLD gates: {len(HOLD_GATES)}")
    for k in HOLD_GATES:
        print(f"    HOLD  {k}")
    checks = run_checks()
    passed = sum(1 for _, ok in checks if ok)
    print(f"\nCHECKS {passed}/{len(checks)}")
    for name, ok in checks:
        if not ok:
            print(f"    FAIL {name}")
    verdict = "PROCEED" if passed == len(checks) else "HOLD"
    print(f"VERDICT {verdict} (sandbox simulation only) | HOLD gates {len(HOLD_GATES)}")
    return 0 if passed == len(checks) else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "demo":
        return demo()
    cmd = argv[0]
    if cmd == "checks":
        checks = run_checks()
        for name, ok in checks:
            print(f"{'PASS' if ok else 'FAIL'} {name}")
        print(f"CHECKS {sum(1 for _, ok in checks if ok)}/{len(checks)}")
        return 0 if all(ok for _, ok in checks) else 1
    if cmd == "aero":
        print(json.dumps(aero_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "levitation":
        print(json.dumps(levitation_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "trip":
        print(json.dumps(trip_phases(), indent=2, sort_keys=True))
        print(json.dumps(trip_profile(), indent=2, sort_keys=True))
        print(json.dumps(energy_comparison(), indent=2, sort_keys=True))
        return 0
    if cmd == "pressure":
        print(json.dumps(pressure_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "braking":
        print(json.dumps(braking_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "thermal":
        print(json.dumps(thermal_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "classify":
        print(json.dumps(regime_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "brains":
        print(json.dumps(brains_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "holds":
        for k, val in HOLD_GATES.items():
            print(f"{k}: {val}")
        return 0
    if cmd == "hold-demo":
        action = argv[1] if len(argv) > 1 else "live_passenger_operation"
        print(f"{action}: {HOLD_GATES.get(action, 'PROCEED - not gated')}")
        return 2 if gate(action) == "HOLD" else 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
