# attendance/forms.py

from django import forms
from django.contrib.auth.models import User
from django.forms import inlineformset_factory
from django.utils.text import slugify
from .models import Employee, AttendanceRecord, Category, Department
from .models import (
    EmployeeEducation,
    EmployeeCertification,
    EmployeeWorkExperience,
    EmployeeDocument,
    Applicant,
    OnboardingInvitation,
    AdminReport,
    AttendanceException,
    AttendanceExceptionType,
    Organization,
    AttendanceSettings,
    LeaveType,
    LeaveRequest,
    OnboardingStage,
    OnboardingTask,
    PayrollRun,
)


EMPLOYEE_SEARCH_PLACEHOLDER = 'Search employee name, ID, email, department'


def searchable_employee_select_attrs(extra_class=''):
    classes = 'form-select'
    if extra_class:
        classes = f'{classes} {extra_class}'
    return {
        'class': classes,
        'data-searchable-select': 'true',
        'data-search-placeholder': EMPLOYEE_SEARCH_PLACEHOLDER,
    }


def employee_choice_label(employee):
    details = [
        employee.display_name,
        employee.employee_id,
        employee.email,
    ]
    if employee.department_id:
        details.append(employee.department.name)
    return ' - '.join(detail for detail in details if detail)


class EmployeeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return employee_choice_label(obj)


class EmployeeForm(forms.ModelForm):
    """Form for adding/editing employees with category-specific fields"""

    AREA_OF_INTEREST_CHOICES = [
        ('software_development', 'Software Development'),
        ('ui_ux_design', 'UI/UX Design'),
        ('cybersecurity', 'Cybersecurity'),
        ('data_science', 'Data Science'),
        ('artificial_intelligence', 'Artificial Intelligence'),
        ('cloud_computing', 'Cloud Computing'),
        ('networking', 'Networking'),
        ('devops', 'DevOps'),
        ('digital_marketing', 'Digital Marketing'),
        ('content_creation', 'Content Creation'),
        ('other', 'Other'),
    ]

    area_of_interest = forms.MultipleChoiceField(
        choices=AREA_OF_INTEREST_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'intern-interest-options'}),
    )
    
    class Meta:
        model = Employee
        fields = [
            'category', 'profile_photo', 'title', 'first_name', 'middle_name', 'last_name', 
            'email', 'personal_email', 'phone', 'alternative_phone', 'gender',
            'date_of_birth', 'nationality', 'marital_status', 'religion',
            'blood_group', 'genotype', 'allergies_or_medical_conditions',
            'emergency_medical_contact_name', 'emergency_medical_contact_relationship',
            'emergency_medical_contact_phone',
            'residential_address', 'permanent_address', 'city', 'state',
            'country', 'postal_code', 'local_government',
            'emergency_contact_name', 'emergency_contact_relationship', 'emergency_contact_phone',
            'next_of_kin_name', 'next_of_kin_relationship', 'next_of_kin_phone',
            'next_of_kin_email', 'next_of_kin_address',
            'department', 'position', 'line_manager',
            'hire_date', 'end_date', 'probation_end_date', 'institution',
            'faculty', 'academic_department', 'qualification_obtained', 'field_of_study',
            'year_of_graduation', 'class_of_degree', 'student_id', 'current_level',
            'expected_graduation_date', 'academic_supervisor_name',
            'academic_supervisor_phone', 'academic_supervisor_email',
            'internship_type', 'internship_type_other', 'area_of_interest',
            'area_of_interest_other', 'preferred_department',
            'skill_html_css', 'skill_javascript', 'skill_python', 'skill_java',
            'skill_c_cpp', 'skill_django', 'skill_react', 'skill_nodejs',
            'skill_ui_ux', 'skill_networking', 'skill_cybersecurity',
            'other_technical_skill', 'skill_other', 'relevant_skills_projects',
            'supervisor',
            'nin_number', 'passport_number', 'passport_expiry_date',
            'tin_number', 'drivers_license_number',
            'work_permit_number', 'work_permit_expiry_date',
            'bank_name', 'bank_account_name', 'bank_account_number', 'bank_branch',
            'pension_rsa_pin', 'pension_fund_administrator',
            'basic_salary', 'housing_allowance', 'transport_allowance', 'other_allowances',
            'tax_deduction', 'pension_deduction', 'other_deductions',
            'employment_status', 'is_active'
        ]
        widgets = {
            'category': forms.Select(attrs={
                'class': 'form-select',
                'id': 'category-select'
            }),
            'profile_photo': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'title': forms.Select(attrs={'class': 'form-select'}),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'First name'
            }),
            'middle_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Middle name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Surname'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Work email (used for kiosk)'
            }),
            'personal_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Personal email (optional)'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Phone number'
            }),
            'alternative_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Alternative phone number'
            }),
            'gender': forms.Select(attrs={'class': 'form-select'}),
            'date_of_birth': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'nationality': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nationality'
            }),
            'marital_status': forms.Select(attrs={'class': 'form-select'}),
            'religion': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Religion'
            }),
            'blood_group': forms.Select(attrs={'class': 'form-select'}),
            'genotype': forms.Select(attrs={'class': 'form-select'}),
            'allergies_or_medical_conditions': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Emergency-relevant allergies or medical conditions'
            }),
            'emergency_medical_contact_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Medical emergency contact name'
            }),
            'emergency_medical_contact_relationship': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Relationship or role'
            }),
            'emergency_medical_contact_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Medical emergency contact phone'
            }),
            'residential_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Current residential address'
            }),
            'permanent_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Permanent home address'
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'City'
            }),
            'state': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'State'
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Country'
            }),
            'postal_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Postal code'
            }),
            'local_government': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Local government area'
            }),
            'emergency_contact_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Emergency contact full name'
            }),
            'emergency_contact_relationship': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Relationship'
            }),
            'emergency_contact_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Emergency contact phone'
            }),
            'next_of_kin_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Next of kin full name'
            }),
            'next_of_kin_relationship': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Relationship'
            }),
            'next_of_kin_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Next of kin phone'
            }),
            'next_of_kin_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Next of kin email'
            }),
            'next_of_kin_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Next of kin address'
            }),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'position': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Software Developer, Intern, Student'
            }),
            'line_manager': forms.Select(attrs=searchable_employee_select_attrs()),
            'hire_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'placeholder': 'Start date'
            }),
            'end_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'placeholder': 'Expected end date (interns/students)'
            }),
            'institution': forms.TextInput(attrs={
                'class': 'form-control intern-student-field',
                'placeholder': 'University/School name'
            }),
            'faculty': forms.TextInput(attrs={
                'class': 'form-control intern-field',
                'placeholder': 'Faculty or school'
            }),
            'academic_department': forms.TextInput(attrs={
                'class': 'form-control intern-field',
                'placeholder': 'Academic department'
            }),
            'qualification_obtained': forms.TextInput(attrs={
                'class': 'form-control intern-student-field',
                'placeholder': 'Qualification obtained'
            }),
            'field_of_study': forms.TextInput(attrs={
                'class': 'form-control intern-student-field',
                'placeholder': 'Course or program'
            }),
            'year_of_graduation': forms.NumberInput(attrs={
                'class': 'form-control intern-student-field',
                'placeholder': 'Year of graduation',
                'min': 1900
            }),
            'class_of_degree': forms.TextInput(attrs={
                'class': 'form-control intern-student-field',
                'placeholder': 'Class of degree'
            }),
            'student_id': forms.TextInput(attrs={
                'class': 'form-control student-field',
                'placeholder': 'School ID number'
            }),
            'current_level': forms.TextInput(attrs={
                'class': 'form-control intern-field',
                'placeholder': 'e.g., 300 Level, HND 2, Final Year'
            }),
            'expected_graduation_date': forms.DateInput(attrs={
                'class': 'form-control intern-field',
                'type': 'date'
            }),
            'academic_supervisor_name': forms.TextInput(attrs={
                'class': 'form-control intern-field',
                'placeholder': 'Academic supervisor full name'
            }),
            'academic_supervisor_phone': forms.TextInput(attrs={
                'class': 'form-control intern-field',
                'placeholder': 'Academic supervisor phone'
            }),
            'academic_supervisor_email': forms.EmailInput(attrs={
                'class': 'form-control intern-field',
                'placeholder': 'Academic supervisor email'
            }),
            'internship_type': forms.Select(attrs={'class': 'form-select intern-field'}),
            'internship_type_other': forms.TextInput(attrs={
                'class': 'form-control intern-field',
                'placeholder': 'Specify internship type'
            }),
            'area_of_interest_other': forms.TextInput(attrs={
                'class': 'form-control intern-field',
                'placeholder': 'Specify other area of interest'
            }),
            'preferred_department': forms.TextInput(attrs={
                'class': 'form-control intern-field',
                'placeholder': 'Preferred company department'
            }),
            'skill_html_css': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'skill_javascript': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'skill_python': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'skill_java': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'skill_c_cpp': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'skill_django': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'skill_react': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'skill_nodejs': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'skill_ui_ux': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'skill_networking': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'skill_cybersecurity': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'other_technical_skill': forms.TextInput(attrs={
                'class': 'form-control intern-field',
                'placeholder': 'Other skill'
            }),
            'skill_other': forms.Select(attrs={'class': 'form-select intern-field skill-level-select'}),
            'relevant_skills_projects': forms.Textarea(attrs={
                'class': 'form-control intern-field',
                'rows': 4,
                'placeholder': 'List other relevant skills, certifications, projects, portfolio links, or achievements'
            }),
            'supervisor': forms.Select(attrs=searchable_employee_select_attrs('intern-student-field')),
            'probation_end_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'nin_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'NIN number'
            }),
            'passport_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Passport number'
            }),
            'passport_expiry_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'tin_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'TIN'
            }),
            'drivers_license_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': "Driver's license number"
            }),
            'work_permit_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Work permit or visa permit number'
            }),
            'work_permit_expiry_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'bank_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Bank name'}),
            'bank_account_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Account name'}),
            'bank_account_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Account number'}),
            'bank_branch': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Branch'}),
            'pension_rsa_pin': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'RSA PIN'}),
            'pension_fund_administrator': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Pension fund administrator'}),
            'basic_salary': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'housing_allowance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'transport_allowance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'other_allowances': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'tax_deduction': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'pension_deduction': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'other_deductions': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'employment_status': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

        if self.organization and not self.instance.pk:
            self.instance.organization = self.organization

        if self.instance.pk and self.instance.area_of_interest:
            self.initial['area_of_interest'] = [
                item.strip()
                for item in self.instance.area_of_interest.split(',')
                if item.strip()
            ]

        if self.organization:
            self.fields['category'].queryset = Category.objects.filter(
                organization=self.organization
            ).order_by('name')
            self.fields['department'].queryset = Department.objects.filter(
                organization=self.organization,
                is_active=True,
            ).order_by('name')
        
        # Filter supervisor choices to only Staff
        staff_categories = Category.objects.filter(code='STAFF')
        if self.organization:
            staff_categories = staff_categories.filter(organization=self.organization)
        staff_category = staff_categories.first()
        if staff_category:
            supervisor_qs = Employee.objects.filter(
                category=staff_category,
                is_active=True
            )
            if self.organization:
                supervisor_qs = supervisor_qs.filter(organization=self.organization)
            self.fields['supervisor'].queryset = supervisor_qs.select_related('category', 'department')
        else:
            self.fields['supervisor'].queryset = Employee.objects.none()

        line_manager_qs = Employee.objects.filter(
            is_active=True
        )
        if self.organization:
            line_manager_qs = line_manager_qs.filter(organization=self.organization)
        self.fields['line_manager'].queryset = line_manager_qs.select_related('category', 'department').order_by('first_name', 'last_name')
        if self.instance.pk:
            self.fields['line_manager'].queryset = self.fields['line_manager'].queryset.exclude(pk=self.instance.pk)
            self.fields['supervisor'].queryset = self.fields['supervisor'].queryset.exclude(pk=self.instance.pk)
        self.fields['line_manager'].label_from_instance = employee_choice_label
        self.fields['supervisor'].label_from_instance = employee_choice_label
        
        # Make fields required based on category (handled by JS, but set initial)
        self.fields['department'].required = False
        self.fields['supervisor'].required = False
        self.fields['line_manager'].required = False
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            email = email.lower().strip()
            qs = Employee.objects.filter(email=email)
            if self.organization:
                qs = qs.filter(organization=self.organization)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('A person with this email already exists.')
        return email

    def clean_area_of_interest(self):
        values = self.cleaned_data.get('area_of_interest') or []
        return ','.join(values)
    
    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')

        # Staff-specific validation (birthday is now optional for all)
        if category and category.code == 'STAFF':
            if not cleaned_data.get('hire_date'):
                self.add_error('hire_date', 'Hire date is required for Staff.')
            if not cleaned_data.get('department'):
                self.add_error('department', 'Department is required for Staff.')

        # Intern-specific validation
        if category and category.code == 'INTERN':
            if not cleaned_data.get('hire_date'):
                self.add_error('hire_date', 'Start date is required for Interns.')
            if not cleaned_data.get('end_date'):
                self.add_error('end_date', 'End date is required for Interns.')
            if not cleaned_data.get('institution'):
                self.add_error('institution', 'Institution is required for Interns.')
            if not cleaned_data.get('field_of_study'):
                self.add_error('field_of_study', 'Course of study is required for Interns.')
            if not cleaned_data.get('student_id'):
                self.add_error('student_id', 'Matriculation number is required for Interns.')
            if not cleaned_data.get('internship_type'):
                self.add_error('internship_type', 'Internship type is required for Interns.')
            if cleaned_data.get('internship_type') == 'other' and not cleaned_data.get('internship_type_other'):
                self.add_error('internship_type_other', 'Please specify the internship type.')

        # Student-specific validation
        if category and category.code == 'STUDENT':
            if not cleaned_data.get('hire_date'):
                self.add_error('hire_date', 'Start date is required for Students.')
            if not cleaned_data.get('end_date'):
                self.add_error('end_date', 'End date is required for Students.')
            if not cleaned_data.get('institution'):
                self.add_error('institution', 'Institution is required for Students.')
            if not cleaned_data.get('student_id'):
                self.add_error('student_id', 'Student ID is required.')

        return cleaned_data


class ManualAttendanceForm(forms.Form):
    """Form for HR to manually add attendance records"""

    ENTRY_TYPE_CHOICES = [
        ('work_session', 'Work Session'),
        ('exception', 'Attendance Exception'),
    ]

    entry_type = forms.ChoiceField(
        choices=ENTRY_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='work_session'
    )

    employee = EmployeeChoiceField(
        queryset=Employee.objects.filter(is_active=True, employment_status='active'),
        widget=forms.Select(attrs=searchable_employee_select_attrs()),
        empty_label="Select Person"
    )

    check_in_time = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        }),
        help_text="Date and time of check-in"
    )
    
    check_out_time = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        }),
        help_text="Leave blank if still working"
    )

    exception_type = forms.ModelChoiceField(
        required=False,
        queryset=AttendanceExceptionType.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='Select exception type'
    )

    exception_start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    exception_end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Optional notes or approval context'
        })
    )

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        # Group employees by category in dropdown
        employee_qs = Employee.objects.filter(
            is_active=True, 
            employment_status='active'
        )
        exception_qs = AttendanceExceptionType.objects.filter(
            is_active=True
        )
        if self.organization:
            employee_qs = employee_qs.filter(organization=self.organization)
            exception_qs = exception_qs.filter(organization=self.organization)
        self.fields['employee'].queryset = employee_qs.select_related(
            'category',
            'department',
        ).order_by('category__name', 'first_name')
        self.fields['exception_type'].queryset = exception_qs.order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        entry_type = cleaned_data.get('entry_type')
        check_in = cleaned_data.get('check_in_time')
        check_out = cleaned_data.get('check_out_time')
        exception_type = cleaned_data.get('exception_type')
        exception_start_date = cleaned_data.get('exception_start_date')
        exception_end_date = cleaned_data.get('exception_end_date')

        if entry_type == 'work_session':
            if not check_in:
                self.add_error('check_in_time', 'Check-in time is required for a work session.')
            if check_in and check_out and check_out <= check_in:
                self.add_error('check_out_time', 'Check-out time must be after check-in time.')
        elif entry_type == 'exception':
            if not exception_type:
                self.add_error('exception_type', 'Select an exception type.')
            if not exception_start_date:
                self.add_error('exception_start_date', 'Start date is required for an attendance exception.')
            if not exception_end_date:
                self.add_error('exception_end_date', 'End date is required for an attendance exception.')
            if exception_start_date and exception_end_date and exception_end_date < exception_start_date:
                self.add_error('exception_end_date', 'End date cannot be earlier than the start date.')

        return cleaned_data


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name', 'slug', 'email', 'phone', 'address', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Organization name'
            }),
            'slug': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'organization-url-name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'contact@company.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Phone number'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Office address'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_slug(self):
        slug = self.cleaned_data.get('slug')
        name = self.cleaned_data.get('name', '')
        slug = slugify(slug or name)
        if not slug:
            raise forms.ValidationError('Enter a valid organization URL slug.')

        qs = Organization.objects.filter(slug=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('An organization already uses this slug.')
        return slug


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'code', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Department name'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Short code'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional description'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

    def clean_code(self):
        return (self.cleaned_data.get('code') or '').strip().upper()

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        if commit:
            instance.save()
        return instance


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'code', 'icon', 'color']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category name'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Short code'}),
            'icon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Bootstrap icon class'}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'primary, success, info'}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

    def clean_code(self):
        return (self.cleaned_data.get('code') or '').strip().upper()

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        if commit:
            instance.save()
        return instance


class AttendanceSettingsForm(forms.ModelForm):
    class Meta:
        model = AttendanceSettings
        fields = ['workday_start', 'late_threshold', 'birthday_reminder_days', 'internship_reminder_days']
        widgets = {
            'workday_start': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'late_threshold': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'birthday_reminder_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'internship_reminder_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }


class BirthdayMessageTemplateForm(forms.ModelForm):
    class Meta:
        model = AttendanceSettings
        fields = ['birthday_message_subject', 'birthday_message_body']
        widgets = {
            'birthday_message_subject': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Happy Birthday, {first_name}!',
            }),
            'birthday_message_body': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 12,
            }),
        }


class AttendanceExceptionTypeForm(forms.ModelForm):
    class Meta:
        model = AttendanceExceptionType
        fields = ['name', 'code', 'description', 'color', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Public Holiday'
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. public_holiday'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional policy note or description'
            }),
            'color': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'primary, success, warning, info, danger'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_code(self):
        code = self.cleaned_data.get('code', '')
        return code.strip().lower().replace(' ', '_')

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        if commit:
            instance.save()
        return instance


class LeaveTypeForm(forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = [
            'name',
            'code',
            'annual_entitlement_days',
            'color',
            'requires_attachment',
            'is_paid',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Annual Leave'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'annual_leave'}),
            'annual_entitlement_days': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'success, warning, info'}),
            'requires_attachment': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_paid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

    def clean_code(self):
        code = self.cleaned_data.get('code', '')
        return slugify(code).replace('-', '_')

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        if commit:
            instance.save()
        return instance


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ['employee', 'leave_type', 'start_date', 'end_date', 'day_part', 'reason']
        widgets = {
            'employee': forms.Select(attrs=searchable_employee_select_attrs()),
            'leave_type': forms.Select(attrs={'class': 'form-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'day_part': forms.Select(attrs={'class': 'form-select'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Reason or handover notes'}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        self.employee = kwargs.pop('employee', None)
        super().__init__(*args, **kwargs)
        employee_qs = Employee.objects.filter(is_active=True).select_related('category', 'department')
        leave_type_qs = LeaveType.objects.filter(is_active=True)
        if self.organization:
            employee_qs = employee_qs.filter(organization=self.organization)
            leave_type_qs = leave_type_qs.filter(organization=self.organization)
        self.fields['employee'].queryset = employee_qs.order_by('first_name', 'last_name')
        self.fields['employee'].label_from_instance = employee_choice_label
        self.fields['leave_type'].queryset = leave_type_qs.order_by('name')
        if self.employee:
            self.fields['employee'].required = False
            self.fields['employee'].widget = forms.HiddenInput()
            self.fields['employee'].initial = self.employee

    def clean(self):
        cleaned_data = super().clean()
        if self.employee:
            cleaned_data['employee'] = self.employee
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        day_part = cleaned_data.get('day_part')

        if start_date and end_date and end_date < start_date:
            self.add_error('end_date', 'End date cannot be earlier than start date.')
        if start_date and end_date and day_part != 'full_day' and start_date != end_date:
            self.add_error('day_part', 'Half-day leave can only be used for a single date.')
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        instance.manager_approval_status = 'not_required'
        if commit:
            instance.save()
        return instance


class LeaveReviewForm(forms.Form):
    review_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Optional review note',
        })
    )


class EmployeeAccountForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'employee@company.com'})
    )
    password = forms.CharField(
        min_length=8,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Temporary password'})
    )

    def __init__(self, *args, **kwargs):
        self.employee = kwargs.pop('employee', None)
        super().__init__(*args, **kwargs)
        if self.employee and not self.is_bound:
            base_username = self.employee.email.split('@')[0] if self.employee.email else self.employee.employee_id.lower()
            self.fields['username'].initial = slugify(base_username).replace('-', '_')
            self.fields['email'].initial = self.employee.email

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('A user account already uses this email.')
        return email


class ApplicantInvitationForm(forms.ModelForm):
    class Meta:
        model = Applicant
        fields = ['first_name', 'middle_name', 'last_name', 'email', 'phone', 'gender', 'category', 'department', 'position', 'cover_note']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Middle name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'candidate@example.com'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'}),
            'gender': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'position': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Role or position'}),
            'cover_note': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Optional note to the applicant'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        category_qs = Category.objects.none()
        department_qs = Department.objects.none()
        if organization:
            category_qs = Category.objects.filter(organization=organization).order_by('name')
            department_qs = Department.objects.filter(organization=organization, is_active=True).order_by('name')
        self.fields['category'].queryset = category_qs
        self.fields['department'].queryset = department_qs
        self.fields['department'].required = False

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if self.organization and Employee.objects.filter(organization=self.organization, email__iexact=email).exists():
            raise forms.ValidationError('An employee already exists with this email. Use existing employee onboarding instead.')
        if self.organization and Applicant.objects.filter(organization=self.organization, email__iexact=email).exists():
            raise forms.ValidationError('An applicant already exists with this email.')
        return email

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.email = instance.email.lower()
        if self.organization:
            instance.organization = self.organization
        if commit:
            instance.save()
        return instance


class ExistingEmployeeOnboardingInviteForm(forms.Form):
    employee = EmployeeChoiceField(
        queryset=Employee.objects.none(),
        widget=forms.Select(attrs=searchable_employee_select_attrs()),
        empty_label='Select employee',
    )
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Optional message to include in the setup email',
        })
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields['employee'].queryset = Employee.objects.filter(
                organization=organization,
                is_active=True,
            ).select_related('category', 'department').order_by('first_name', 'last_name')


class ApplicantApplicationForm(forms.ModelForm):
    class Meta:
        model = Applicant
        fields = ['first_name', 'middle_name', 'last_name', 'phone', 'gender', 'department', 'position', 'cover_note']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'}),
            'gender': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'position': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Role or position'}),
            'cover_note': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Brief application note, skills, or experience summary'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        department_qs = Department.objects.none()
        if organization:
            department_qs = Department.objects.filter(organization=organization, is_active=True).order_by('name')
        self.fields['department'].queryset = department_qs
        self.fields['department'].required = False


class EmployeeOnboardingSetupForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Choose username'}),
    )
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Choose password'}),
    )

    def __init__(self, *args, employee=None, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)
        if employee and not self.is_bound:
            base_username = employee.email.split('@')[0] if employee.email else employee.employee_id.lower()
            self.fields['username'].initial = slugify(base_username).replace('-', '_')
        if employee and employee.user:
            self.fields['username'].initial = employee.user.username
            self.fields['username'].disabled = True
            self.fields['password'].label = 'New Password'

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if self.employee and self.employee.user and username == self.employee.user.username:
            return username
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username


class OnboardingStageForm(forms.ModelForm):
    class Meta:
        model = OnboardingStage
        fields = ['title', 'description', 'order', 'color', 'is_active']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Stage title'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional stage description'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'color': forms.Select(
                attrs={'class': 'form-select'},
                choices=[
                    ('primary', 'Primary'),
                    ('secondary', 'Secondary'),
                    ('success', 'Success'),
                    ('danger', 'Danger'),
                    ('warning', 'Warning'),
                    ('info', 'Info'),
                    ('dark', 'Dark'),
                ],
            ),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        if commit:
            instance.save()
        return instance


class AdminReportForm(forms.ModelForm):
    class Meta:
        model = AdminReport
        fields = [
            'title',
            'report_type',
            'tone',
            'event_date',
            'related_employee',
            'related_department',
            'body',
            'action_taken',
            'status',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Short report title'}),
            'report_type': forms.Select(attrs={'class': 'form-select'}),
            'tone': forms.Select(attrs={'class': 'form-select'}),
            'event_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'related_employee': forms.Select(attrs=searchable_employee_select_attrs()),
            'related_department': forms.Select(attrs={'class': 'form-select'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 8, 'placeholder': 'Write the report, feedback, observation, or event details'}),
            'action_taken': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Optional action taken, recommendation, or follow-up'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        employee_qs = Employee.objects.none()
        department_qs = Department.objects.none()
        if organization:
            employee_qs = Employee.objects.filter(
                organization=organization,
                is_active=True,
            ).select_related('category', 'department').order_by('first_name', 'last_name')
            department_qs = Department.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by('name')
        self.fields['related_employee'].queryset = employee_qs
        self.fields['related_employee'].required = False
        self.fields['related_employee'].label_from_instance = employee_choice_label
        self.fields['related_department'].queryset = department_qs
        self.fields['related_department'].required = False
        self.fields['action_taken'].required = False

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        if commit:
            instance.save()
        return instance


class PayrollRunForm(forms.ModelForm):
    class Meta:
        model = PayrollRun
        fields = ['title', 'payroll_month', 'notes']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. May 2026 Payroll'}),
            'payroll_month': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional payroll notes'}),
        }

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)

    def clean_payroll_month(self):
        payroll_month = self.cleaned_data['payroll_month']
        return payroll_month.replace(day=1)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization:
            instance.organization = self.organization
        if commit:
            instance.save()
        return instance


class DateFilterForm(forms.Form):
    """Form for filtering attendance by date"""
    
    date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        }),
        required=False
    )
    
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'placeholder': 'From'
        }),
        required=False
    )
    
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'placeholder': 'To'
        }),
        required=False
    )
    
    employee = EmployeeChoiceField(
        queryset=Employee.objects.filter(is_active=True).select_related('category', 'department'),
        widget=forms.Select(attrs=searchable_employee_select_attrs()),
        required=False,
        empty_label="All People"
    )

    category = forms.ModelChoiceField(
        queryset=Category.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False,
        empty_label="All Categories"
    )

    department = forms.ModelChoiceField(
        queryset=Department.objects.filter(is_active=True).order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False,
        empty_label="All Departments"
    )

    employment_status = forms.ChoiceField(
        choices=[('', 'All Employment Status')] + list(Employee.EMPLOYMENT_STATUS),
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False
    )

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search name, email, or employee ID'
        })
    )

    def __init__(self, *args, **kwargs):
        self.organization = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        employee_qs = Employee.objects.filter(is_active=True)
        category_qs = Category.objects.order_by('name')
        department_qs = Department.objects.filter(is_active=True).order_by('name')
        if self.organization:
            employee_qs = employee_qs.filter(organization=self.organization)
            category_qs = category_qs.filter(organization=self.organization)
            department_qs = department_qs.filter(organization=self.organization)
        self.fields['employee'].queryset = employee_qs.select_related('category', 'department').order_by('first_name', 'last_name')
        self.fields['category'].queryset = category_qs
        self.fields['department'].queryset = department_qs


class EmployeeEducationForm(forms.ModelForm):
    class Meta:
        model = EmployeeEducation
        fields = ['qualification_obtained', 'institution', 'field_of_study', 'year_of_graduation', 'class_of_degree']
        widgets = {
            'qualification_obtained': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Qualification obtained'}),
            'institution': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Institution'}),
            'field_of_study': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Field of study'}),
            'year_of_graduation': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Year', 'min': 1900}),
            'class_of_degree': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Class of degree'}),
        }


class EmployeeCertificationForm(forms.ModelForm):
    class Meta:
        model = EmployeeCertification
        fields = ['certification_name', 'issuing_body', 'date_obtained', 'expiry_date']
        widgets = {
            'certification_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Certification name'}),
            'issuing_body': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Issuing body'}),
            'date_obtained': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expiry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


class EmployeeWorkExperienceForm(forms.ModelForm):
    class Meta:
        model = EmployeeWorkExperience
        fields = ['employer_name', 'job_title', 'start_date', 'end_date', 'reason_for_leaving', 'skills_and_competence']
        widgets = {
            'employer_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Previous employer'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Job title'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'reason_for_leaving': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Reason for leaving'}),
            'skills_and_competence': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Skills and competence'}),
        }


class EmployeeDocumentForm(forms.ModelForm):
    class Meta:
        model = EmployeeDocument
        fields = ['document_type', 'title', 'file', 'issue_date', 'expiry_date', 'notes']
        widgets = {
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Document title'}),
            'file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'issue_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expiry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional notes'}),
        }


class OnboardingTaskForm(forms.ModelForm):
    class Meta:
        model = OnboardingTask
        fields = ['employee', 'stage', 'title', 'category', 'status', 'assigned_to', 'due_date', 'notes']
        widgets = {
            'employee': forms.Select(attrs=searchable_employee_select_attrs()),
            'stage': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Task title'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'assigned_to': forms.Select(attrs={'class': 'form-select'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional notes or instructions'}),
        }

    def __init__(self, *args, organization=None, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['stage'].queryset = OnboardingStage.objects.none()
        self.fields['stage'].required = False
        if organization:
            self.fields['employee'].queryset = Employee.objects.filter(
                organization=organization,
                is_active=True,
            ).select_related('category', 'department').order_by('first_name', 'last_name')
            self.fields['employee'].label_from_instance = employee_choice_label
            self.fields['stage'].queryset = OnboardingStage.objects.filter(
                organization=organization,
                is_active=True,
            ).order_by('order', 'title')
            self.fields['stage'].required = False
            self.fields['assigned_to'].queryset = User.objects.filter(
                organization_memberships__organization=organization,
                organization_memberships__is_active=True,
            ).distinct().order_by('first_name', 'last_name', 'username')
        if employee:
            self.fields['employee'].initial = employee
            self.fields['employee'].widget = forms.HiddenInput()


EmployeeEducationFormSet = inlineformset_factory(
    Employee,
    EmployeeEducation,
    form=EmployeeEducationForm,
    extra=1,
    can_delete=True,
)

EmployeeCertificationFormSet = inlineformset_factory(
    Employee,
    EmployeeCertification,
    form=EmployeeCertificationForm,
    extra=1,
    can_delete=True,
)

EmployeeWorkExperienceFormSet = inlineformset_factory(
    Employee,
    EmployeeWorkExperience,
    form=EmployeeWorkExperienceForm,
    extra=1,
    can_delete=True,
)

EmployeeDocumentFormSet = inlineformset_factory(
    Employee,
    EmployeeDocument,
    form=EmployeeDocumentForm,
    extra=1,
    can_delete=True,
)


class OrganizationBrandingForm(forms.ModelForm):
    remove_logo = forms.BooleanField(required=False)
    brand_color = forms.RegexField(
        regex=r'^#[0-9A-Fa-f]{6}$',
        error_messages={'invalid': 'Enter a valid hex color like #0A0A0A.'},
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '#0A0A0A', 'maxlength': 7}),
    )
    timezone = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Africa/Lagos', 'list': 'tz-list'}),
    )

    class Meta:
        model = Organization
        fields = ['name', 'logo', 'brand_color', 'timezone']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.png,.jpg,.jpeg,.webp'}),
        }

    def clean_timezone(self):
        from .models import validate_iana_timezone
        value = (self.cleaned_data.get('timezone') or '').strip()
        validate_iana_timezone(value)
        return value

    def clean_logo(self):
        from PIL import Image
        f = self.cleaned_data.get('logo')
        if not f:
            return f
        if f.size > 2 * 1024 * 1024:
            raise forms.ValidationError('Logo must be 2MB or smaller.')
        ext = (f.name.rsplit('.', 1)[-1] if '.' in f.name else '').lower()
        if ext not in {'png', 'jpg', 'jpeg', 'webp'}:
            raise forms.ValidationError('Logo must be PNG, JPG or WebP (SVG not allowed).')
        try:
            img = Image.open(f)
            img.verify()
        except Exception:
            raise forms.ValidationError('Uploaded file is not a valid image.')
        f.seek(0)
        return f

    def clean_brand_color(self):
        from .branding import normalize_hex
        return normalize_hex(self.cleaned_data.get('brand_color', ''))

    def save(self, commit=True):
        instance = super().save(commit=False)
        logo = self.cleaned_data.get('logo')
        if logo:
            # Resize to a sensible maximum, keep format, keep random filename.
            from io import BytesIO
            from django.core.files.base import ContentFile
            from PIL import Image
            try:
                logo.seek(0)
                img = Image.open(logo)
                img.load()
                if img.width > 512 or img.height > 512:
                    img.thumbnail((512, 512))
                    buffer = BytesIO()
                    fmt = (img.format or 'PNG').upper()
                    if fmt == 'JPG':
                        fmt = 'JPEG'
                    save_kwargs = {'format': fmt}
                    if fmt == 'JPEG':
                        save_kwargs['quality'] = 85
                    img.save(buffer, **save_kwargs)
                    logo = ContentFile(buffer.getvalue(), name=logo.name)
                    instance.logo = logo
            except Exception:
                pass
        if commit:
            instance.save()
        return instance
