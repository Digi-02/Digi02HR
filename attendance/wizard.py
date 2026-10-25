"""Company setup wizard — owner/hr_admin guided first-time setup.

Wizard state lives on the Organization model:
  setup_current_step        — step number currently being shown
  setup_completed_steps     — JSON list of step numbers finished/skipped
  setup_completed           — True once every required step is done
"""
from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from zoneinfo import ZoneInfo
from PIL import Image as PILImage

from .models import Organization, AttendanceSettings, OrganizationMembership
from .models import BRAND_COLOR_VALIDATOR
from .branding import normalize_hex, dominant_color
from .organization import user_has_hr_access, get_active_organization


# ---------------------------------------------------------------------------
# Step definitions
# ---------------------------------------------------------------------------

WIZARD_STEPS = [
    {'number': 1, 'id': 'company_details', 'title': 'Company details', 'optional': False},
    {'number': 2, 'id': 'branding', 'title': 'Branding', 'optional': True},
    {'number': 3, 'id': 'dashboard', 'title': 'Dashboard', 'optional': True},
    {'number': 4, 'id': 'email', 'title': 'Company email', 'optional': True},
]

STEP_COMPANY_DETAILS = 1
STEP_BRANDING = 2
STEP_DASHBOARD = 3
STEP_EMAIL = 4
STEP_COMPLETE = 5


def get_step_config(step_number):
    for step in WIZARD_STEPS:
        if step['number'] == step_number:
            return step
    return None


def _require_mailbox():
    return getattr(settings, 'REQUIRE_MAILBOX_SETUP', False)


def next_step_number(current_step, completed_steps):
    """Return the next incomplete step number after current_step, or STEP_COMPLETE."""
    candidate = current_step + 1
    while candidate <= STEP_EMAIL:
        config = get_step_config(candidate)
        if config is None:
            break
        if candidate not in completed_steps:
            return candidate
        candidate += 1
    return STEP_COMPLETE


# ---------------------------------------------------------------------------
# Step forms
# ---------------------------------------------------------------------------

class CompanyDetailsForm(forms.Form):
    """Step 1: Company details — feeds Organization + AttendanceSettings."""

    company_name = forms.CharField(max_length=150, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company name'}))
    industry = forms.CharField(max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Technology'}))
    company_size = forms.CharField(max_length=30, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 1-10'}))
    country = forms.CharField(max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Nigeria'}))
    timezone = forms.CharField(max_length=50, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Africa/Lagos'}))
    workday_start = forms.TimeField(required=True,
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}))
    late_after = forms.TimeField(required=True,
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}))

    def clean_timezone(self):
        value = (self.cleaned_data.get('timezone') or '').strip()
        if not value:
            raise ValidationError('Enter a valid IANA timezone, e.g. Africa/Lagos.')
        try:
            ZoneInfo(value)
        except Exception:
            raise ValidationError('Enter a valid IANA timezone, e.g. Africa/Lagos.')
        return value

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('workday_start')
        late = cleaned.get('late_after')
        if start and late and late <= start:
            self.add_error('late_after', 'Late-after time must be after the workday start time.')
        return cleaned


class BrandingForm(forms.Form):
    """Step 2: Branding — logo upload + brand colour."""

    logo = forms.ImageField(required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}))
    brand_color = forms.CharField(max_length=7, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '#0A0A0A'}))

    def clean_logo(self):
        file = self.cleaned_data.get('logo')
        if file is None:
            return None
        try:
            img = PILImage.open(file)
            img.verify()
        except Exception:
            raise ValidationError('Upload a valid image file (PNG, JPG, WEBP).')
        return file

    def clean_brand_color(self):
        value = (self.cleaned_data.get('brand_color') or '').strip()
        if not value:
            return '#0A0A0A'
        BRAND_COLOR_VALIDATOR(value)
        return normalize_hex(value)


class DashboardForm(forms.Form):
    """Step 3: Customize dashboard — navigation style presets."""

    nav_style = forms.ChoiceField(choices=Organization.NAV_STYLE_CHOICES, required=False,
        widget=forms.Select(attrs={'class': 'form-select'}))
    nav_bg_color = forms.CharField(max_length=7, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '#0A0A0A'}))
    nav_highlight_style = forms.ChoiceField(choices=Organization.NAV_HIGHLIGHT_STYLE_CHOICES,
        required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    nav_highlight_source = forms.ChoiceField(choices=Organization.NAV_HIGHLIGHT_SOURCE_CHOICES,
        required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    nav_highlight_color = forms.CharField(max_length=7, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '#0A0A0A'}))

    def clean_nav_bg_color(self):
        value = (self.cleaned_data.get('nav_bg_color') or '').strip()
        if not value:
            return '#0A0A0A'
        BRAND_COLOR_VALIDATOR(value)
        return normalize_hex(value)

    def clean_nav_highlight_color(self):
        value = (self.cleaned_data.get('nav_highlight_color') or '').strip()
        if not value:
            return '#0A0A0A'
        BRAND_COLOR_VALIDATOR(value)
        return normalize_hex(value)


# ---------------------------------------------------------------------------
# Wizard view
# ---------------------------------------------------------------------------

def _org_for_user(request):
    org = get_active_organization(request)
    if org is None:
        return None
    is_owner_or_hr = (
        request.user.is_superuser
        or OrganizationMembership.objects.filter(
            user=request.user, organization=org, role__in=('owner', 'hr_admin'),
            is_active=True,
        ).exists()
    )
    return org if is_owner_or_hr else None


def setup_wizard(request):
    """Full-page stepper wizard for first-time company setup."""
    org = _org_for_user(request)
    if org is None:
        messages.warning(request, 'Only the company owner or HR admin can run setup.')
        return redirect('dashboard')
    if org.setup_completed:
        return redirect('dashboard')

    current_step = org.setup_current_step or 1
    completed_steps = set(org.setup_completed_steps or [])
    config = get_step_config(current_step)
    if config is None:
        org.setup_completed = True
        org.save(update_fields=['setup_completed'])
        return redirect('setup_complete')

    # --- POST: handle form submission / navigation ---
    if request.method == 'POST':
        action = request.POST.get('action', 'next')

        if action == 'save_later':
            messages.success(request, 'Progress saved. Continue setup when you are ready.')
            return redirect('setup_wizard')

        if action == 'later':
            # "I'll do this later" — only valid for optional Step 4 when
            # REQUIRE_MAILBOX_SETUP is False.
            if current_step == STEP_EMAIL and not _require_mailbox():
                completed_steps.add(current_step)
                org.setup_completed_steps = sorted(completed_steps)
                org.setup_completed = True
                org.save(update_fields=['setup_completed_steps', 'setup_completed'])
                messages.success(request, 'Setup complete. Welcome to your workspace.')
                return redirect('setup_complete')
            messages.error(request, 'This step cannot be skipped yet.')
            return redirect('setup_wizard')

        if action == 'back':
            prev = current_step - 1
            while prev >= 1 and get_step_config(prev) is None:
                prev -= 1
            org.setup_current_step = max(1, prev)
            org.save(update_fields=['setup_current_step'])
            return redirect('setup_wizard')

        if action == 'skip':
            if not config['optional']:
                messages.error(request, 'This step is required and cannot be skipped.')
                return redirect('setup_wizard')
            completed_steps.add(current_step)
            org.setup_completed_steps = sorted(completed_steps)
            nxt = next_step_number(current_step, completed_steps)
            if nxt == STEP_COMPLETE:
                org.setup_completed = True
                org.save(update_fields=['setup_completed_steps', 'setup_completed'])
                messages.success(request, 'Setup complete. Welcome to your workspace.')
                return redirect('setup_complete')
            org.setup_current_step = nxt
            org.save(update_fields=['setup_completed_steps', 'setup_current_step'])
            return redirect('setup_wizard')

        # Step form submission
        if current_step == STEP_COMPANY_DETAILS:
            form = CompanyDetailsForm(request.POST)
            if form.is_valid():
                org.name = (form.cleaned_data.get('company_name') or org.name).strip()
                org.industry = (form.cleaned_data.get('industry') or '').strip()
                org.company_size = (form.cleaned_data.get('company_size') or '').strip()
                org.country = (form.cleaned_data.get('country') or '').strip()
                org.timezone = form.cleaned_data['timezone']
                org.save(update_fields=['name', 'industry', 'company_size', 'country', 'timezone'])

                settings_obj = AttendanceSettings.get_solo(org)
                settings_obj.workday_start = form.cleaned_data['workday_start']
                settings_obj.late_threshold = form.cleaned_data['late_after']
                settings_obj.save()

                completed_steps.add(current_step)
                org.setup_completed_steps = sorted(completed_steps)
                nxt = next_step_number(current_step, completed_steps)
                if nxt == STEP_COMPLETE:
                    org.setup_completed = True
                    org.save(update_fields=['setup_completed_steps', 'setup_completed'])
                    messages.success(request, 'Setup complete. Welcome to your workspace.')
                    return redirect('setup_complete')
                org.setup_current_step = nxt
                org.save(update_fields=['setup_completed_steps', 'setup_current_step'])
                messages.success(request, 'Company details saved.')
                return redirect('setup_wizard')
        elif current_step == STEP_BRANDING:
            form = BrandingForm(request.POST, request.FILES)
            if form.is_valid():
                logo = form.cleaned_data.get('logo')
                if logo:
                    org.logo = logo
                    # Detect dominant colour as brand colour suggestion
                    try:
                        org.logo.seek(0)
                        suggested = dominant_color(org.logo)
                        if not form.cleaned_data.get('brand_color'):
                            org.brand_color = suggested
                    except Exception:
                        pass
                if form.cleaned_data.get('brand_color'):
                    org.brand_color = form.cleaned_data['brand_color']
                org.save(update_fields=['logo', 'brand_color'])

                completed_steps.add(current_step)
                org.setup_completed_steps = sorted(completed_steps)
                nxt = next_step_number(current_step, completed_steps)
                if nxt == STEP_COMPLETE:
                    org.setup_completed = True
                    org.save(update_fields=['setup_completed_steps', 'setup_completed'])
                    messages.success(request, 'Setup complete. Welcome to your workspace.')
                    return redirect('setup_complete')
                org.setup_current_step = nxt
                org.save(update_fields=['setup_completed_steps', 'setup_current_step'])
                messages.success(request, 'Branding saved.')
                return redirect('setup_wizard')
        elif current_step == STEP_DASHBOARD:
            form = DashboardForm(request.POST)
            if form.is_valid():
                cd = form.cleaned_data
                if cd.get('nav_style'):
                    org.nav_style = cd['nav_style']
                if cd.get('nav_bg_color'):
                    org.nav_bg_color = cd['nav_bg_color']
                if cd.get('nav_highlight_style'):
                    org.nav_highlight_style = cd['nav_highlight_style']
                if cd.get('nav_highlight_source'):
                    org.nav_highlight_source = cd['nav_highlight_source']
                if cd.get('nav_highlight_color'):
                    org.nav_highlight_color = cd['nav_highlight_color']
                org.save()

                completed_steps.add(current_step)
                org.setup_completed_steps = sorted(completed_steps)
                nxt = next_step_number(current_step, completed_steps)
                if nxt == STEP_COMPLETE:
                    org.setup_completed = True
                    org.save(update_fields=['setup_completed_steps', 'setup_completed'])
                    messages.success(request, 'Setup complete. Welcome to your workspace.')
                    return redirect('setup_complete')
                org.setup_current_step = nxt
                org.save(update_fields=['setup_completed_steps', 'setup_current_step'])
                messages.success(request, 'Dashboard settings saved.')
                return redirect('setup_wizard')
        elif current_step == STEP_EMAIL:
            if _require_mailbox():
                # Mailbox setup is required — must pass connection test before finishing.
                # Re-render step 4 with an error instead of redirecting.
                messages.error(request, 'Company email setup is required before setup can be completed.')
                form = None
                config = get_step_config(STEP_EMAIL)
                total_steps = len([s for s in WIZARD_STEPS])
                completed_count = len(completed_steps)
                pct = int((completed_count / total_steps) * 100) if total_steps else 0
                context = {
                    'organization': org,
                    'step': config,
                    'step_number': STEP_EMAIL,
                    'form': form,
                    'wizard_steps': WIZARD_STEPS,
                    'completed_steps': sorted(completed_steps),
                    'total_steps': total_steps,
                    'completed_count': completed_count,
                    'progress_pct': pct,
                    'require_mailbox': _require_mailbox(),
                    'page_title': f'Setup — {config["title"]}',
                }
                return render(request, 'attendance/wizard/step.html', context)
            else:
                # Optional step — "I'll do this later" link marks it complete.
                completed_steps.add(current_step)
                org.setup_completed_steps = sorted(completed_steps)
                org.setup_completed = True
                org.save(update_fields=['setup_completed_steps', 'setup_completed'])
                messages.success(request, 'Setup complete. Welcome to your workspace.')
                return redirect('setup_complete')

        # If we get here, form was invalid — fall through to re-render with errors
        form = form  # noqa: F821

    # --- GET: show current step ---
    else:
        if current_step == STEP_COMPANY_DETAILS:
            form = CompanyDetailsForm(initial={
                'company_name': org.name,
                'industry': org.industry,
                'company_size': org.company_size,
                'country': org.country,
                'timezone': org.timezone,
                'workday_start': AttendanceSettings.get_solo(org).workday_start,
                'late_after': AttendanceSettings.get_solo(org).late_threshold,
            })
        elif current_step == STEP_BRANDING:
            form = BrandingForm(initial={'brand_color': org.brand_color})
        elif current_step == STEP_DASHBOARD:
            form = DashboardForm(initial={
                'nav_style': org.nav_style,
                'nav_bg_color': org.nav_bg_color,
                'nav_highlight_style': org.nav_highlight_style,
                'nav_highlight_source': org.nav_highlight_source,
                'nav_highlight_color': org.nav_highlight_color,
            })
        elif current_step == STEP_EMAIL:
            form = None  # placeholder step has no form
        else:
            form = None

    total_steps = len([s for s in WIZARD_STEPS])
    completed_count = len(completed_steps)
    pct = int((completed_count / total_steps) * 100) if total_steps else 0

    context = {
        'organization': org,
        'step': config,
        'step_number': current_step,
        'form': form,
        'wizard_steps': WIZARD_STEPS,
        'completed_steps': sorted(completed_steps),
        'total_steps': total_steps,
        'completed_count': completed_count,
        'progress_pct': pct,
        'require_mailbox': _require_mailbox(),
        'page_title': f'Setup — {config["title"]}',
    }
    return render(request, 'attendance/wizard/step.html', context)


def setup_complete(request):
    """Wizard finished — summary and 'Start the tour' link."""
    org = get_active_organization(request)
    if org is None:
        return redirect('dashboard')
    if not org.setup_completed:
        return redirect('setup_wizard')
    return render(request, 'attendance/wizard/complete.html', {
        'organization': org,
        'page_title': 'Setup complete',
    })
