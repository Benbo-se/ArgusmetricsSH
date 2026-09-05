/**
 * Alpine components, so the CSP-friendly build can be used.
 *
 * The standard Alpine build compiles every x-* attribute with
 * `new AsyncFunction(...)`, which is why the Content-Security-Policy needed
 * 'unsafe-eval'. That single directive re-permits the whole class of attack
 * the policy exists to stop, so the expressions move here instead.
 *
 * The CSP build's evaluator is a single lookup:
 *
 *     completeScope[expression]
 *
 * That is the entire grammar. One bare name. No operators, no literals, no
 * arguments, and no dot access: `x-text="user.name"` looks for a scope key
 * literally called "user.name" and finds nothing. So every expression in the
 * templates is now a property or a method defined in a component here, and
 * anything derived is a getter.
 *
 * Two consequences worth knowing before editing a template:
 *
 *   - A component takes no arguments, because `x-data="thing(1)"` is a call
 *     expression and would not parse. Values from the server arrive as data
 *     attributes and are read in init().
 *   - Inside x-for the scope holds only the loop variables, so per-item
 *     fields need a nested component whose getters flatten them. See
 *     toastItem.
 */

/**
 * A two-way binding target for x-model.
 *
 * The CSP build cannot assign to an expression: to write a value back it
 * checks whether the expression resolved to an object carrying get and set,
 * and calls those. A plain property therefore reads fine and silently never
 * saves, which is the kind of bug that passes a page load and fails a form.
 *
 * So every x-model target is a getter returning modelFor(this, 'field').
 */
function modelFor(component, key) {
    return {
        get: () => component[key],
        set: (value) => { component[key] = value },
    }
}

document.addEventListener('alpine:init', () => {

    /**
     * Anything that opens and closes: dropdown, modal, mobile menu, panel.
     *
     * One component rather than a dozen near-identical ones, because they all
     * held a single boolean under a different name (showAddModal, sidebarOpen,
     * mobileMenuOpen) and differed in nothing else.
     */
    Alpine.data('disclosure', () => ({
        open: false,
        toggle() { this.open = !this.open },
        show() { this.open = true },
        close() { this.open = false },
        get isOpen() { return this.open },
        get isClosed() { return !this.open },
        /** The sidebar slides rather than appearing, so it needs a class. */
        get slideClass() {
            return this.open ? 'translate-x-0' : '-translate-x-full'
        },
    }))

    /**
     * The toast stack.
     *
     * Toasts arrive as a window event from dashboard.js and disappear on their
     * own. The timer is kept per toast rather than shifting the oldest after a
     * fixed delay: with the old arrangement, two toasts a second apart made
     * the first timer remove the second one.
     */
    Alpine.data('toasts', () => ({
        toasts: [],
        nextId: 0,

        init() {
            window.addEventListener('toast', (event) => this.add(event.detail))
        },

        add(detail) {
            const toast = {
                id: this.nextId++,
                message: (detail && detail.message) || '',
                type: (detail && detail.type) || 'info',
            }
            this.toasts.push(toast)
            setTimeout(() => this.remove(toast.id), 5000)
        },

        remove(id) {
            this.toasts = this.toasts.filter((t) => t.id !== id)
        },
    }))

    /**
     * One toast, flattened.
     *
     * Exists only because the CSP build cannot read `toast.message` inside the
     * x-for. The loop variable is in scope, so a nested component can reach it
     * through `this` and expose plain names.
     */
    Alpine.data('toastItem', () => ({
        get message() { return this.toast.message },
        get isError() { return this.toast.type === 'error' },
        get isNotError() { return this.toast.type !== 'error' },
        get borderClass() {
            return this.isError ? 'border-red-500' : 'border-blue-500'
        },
        get ariaLive() { return this.isError ? 'assertive' : 'polite' },
    }))

    /**
     * The revenue page's range and currency pickers.
     *
     * Both are read from data attributes rather than passed as arguments,
     * since a component cannot take any. Changing either reloads the page with
     * the new query string, which is what the old inline handler did.
     */
    Alpine.data('revenueControls', () => ({
        range: '',
        currency: '',

        init() {
            this.range = this.$el.dataset.range || ''
            this.currency = this.$el.dataset.currency || ''
        },

        get currentCurrency() { return this.currency },

        /**
         * Highlights whichever range button this is on.
         *
         * A getter cannot take an argument, so the button says which range it
         * represents in a data attribute and this reads it off $el. Alpine
         * injects $el per element, so each button gets its own answer from the
         * one getter.
         */
        get rangeClass() {
            const mine = this.$el.dataset.value
            return mine === this.range
                ? 'bg-blue-50 text-blue-700 border-blue-300'
                : 'bg-white text-gray-700 border-gray-300'
        },

        reload() {
            const url = new URL(window.location.href)
            url.searchParams.set('range', this.range)
            url.searchParams.set('currency', this.currency)
            window.location.href = url.toString()
        },

        /**
         * Applies a filter whose name and value are on the clicked element.
         *
         * Used by the server-rendered country, device and browser lists. The
         * value used to be rendered by Jinja into a JavaScript string literal
         * inside the attribute, so a country name containing an apostrophe
         * ended the string.
         */
        applyFilterFromData(event) {
            const el = event.currentTarget
            const name = el.dataset.filter
            this.filters[name] = el.dataset.value !== undefined
                ? el.dataset.value
                : el.dataset[name]
            this.updateDashboard()
        },

        /** Highlights a server-rendered row when its filter is the active one. */
        get serverRowClass() {
            const el = this.$el
            const name = el.dataset.filter
            const value = el.dataset.value !== undefined
                ? el.dataset.value
                : el.dataset[name]
            return this.filters[name] === value
                ? 'bg-blue-50 border-l-4 border-blue-500'
                : ''
        },

        chooseRange(event) {
            this.range = event.currentTarget.dataset.value
            this.reload()
        },

        chooseCurrency(event) {
            this.currency = event.currentTarget.dataset.value
            this.reload()
        },
    }))
})

document.addEventListener('alpine:init', () => {

    /**
     * The goals page: list, create, edit, delete.
     *
     * The form fields are flat (formName, formEventName) rather than a nested
     * formData object, because x-model has the same one-name restriction as
     * every other binding and `x-model="formData.name"` would look for a key
     * called "formData.name".
     */
    Alpine.data('goalsPage', () => ({
        goals: [],
        createOpen: false,
        deleteOpen: false,
        editingGoal: null,
        deletingGoal: null,
        name: '',
        eventName: '',
        //: True once the event name has been typed in directly, after which
        //: it stops following the label.
        eventNameEdited: false,

        // x-model targets. See modelFor.
        get formName() { return modelFor(this, 'name') },
        get formEventName() { return modelFor(this, 'eventName') },
        loading: false,
        error: null,

        init() {
            const el = document.getElementById('goals-data')
            this.goals = el ? JSON.parse(el.textContent) : []
        },

        get hasGoals() { return this.goals.length > 0 },
        get hasNoGoals() { return this.goals.length === 0 },
        get isCreateOpen() { return this.createOpen },
        get isDeleteOpen() { return this.deleteOpen },
        get hasError() { return !!this.error },
        get isLoading() { return this.loading },
        get isNotLoading() { return !this.loading },
        get modalTitle() { return this.editingGoal ? 'Edit Goal' : 'Create New Goal' },
        get submitLabel() { return this.editingGoal ? 'Update Goal' : 'Create Goal' },
        get saveClass() {
            return this.loading
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700'
        },
        get destroyClass() {
            return this.loading
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-red-600 hover:bg-red-700'
        },
        get deletingGoalName() {
            return this.deletingGoal ? this.deletingGoal.name : ''
        },

        resetForm() {
            this.name = ''
            this.eventName = ''
            this.eventNameEdited = false
            this.editingGoal = null
            this.error = null
        },

        openCreate() {
            this.resetForm()
            this.createOpen = true
        },

        openEdit(goal) {
            this.editingGoal = goal
            this.name = goal.name
            this.eventName = goal.event_name
            // Editing an existing goal: its event name is already the
            // customer's, and renaming the goal must not silently change the
            // name their site is sending.
            this.eventNameEdited = true
            this.error = null
            this.createOpen = true
        },

        openDelete(goal) {
            this.deletingGoal = goal
            this.deleteOpen = true
        },

        closeCreate() {
            this.createOpen = false
            this.resetForm()
        },

        closeDelete() {
            this.deleteOpen = false
            this.deletingGoal = null
        },

        /**
         * Keeps the event name mirroring the label until somebody edits it.
         *
         * The old version only filled it in while it was still empty, and it
         * ran on every keystroke. So typing "Finding proven" set the event
         * name to "f" on the first character and then never touched it again,
         * because it was no longer empty. The goal saved with event_name "f"
         * and matched nothing the site ever sent.
         *
         * Now it re-derives on every keystroke, and stops the moment the
         * event name field is typed in directly.
         */
        generateEventName() {
            if (this.eventNameEdited) return
            this.eventName = this.slugify(this.name)
        },

        /** Marks the event name as the customer's, so it stops following. */
        eventNameTyped() {
            this.eventNameEdited = true
        },

        slugify(value) {
            return (value || '')
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, '_')
                .replace(/^_+|_+$/g, '')
        },

        async saveGoal() {
            this.loading = true
            this.error = null
            const body = { name: this.name, event_name: this.eventName }

            try {
                const editing = this.editingGoal
                const url = editing
                    ? `/api/v1/analytics/goals/${editing.id}?website_id=${window.WEBSITE_ID}`
                    : `/api/v1/analytics/goals?website_id=${window.WEBSITE_ID}`

                const response = await fetch(url, {
                    method: editing ? 'PUT' : 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                })
                const data = await response.json()

                if (!response.ok) {
                    this.error = data.detail || data.message || 'Failed to save goal'
                    return
                }

                if (editing) {
                    const index = this.goals.findIndex((g) => g.id === editing.id)
                    if (index !== -1) this.goals[index] = data
                } else {
                    this.goals.unshift(data)
                }

                const message = editing
                    ? 'Goal updated successfully'
                    : 'Goal created successfully'
                this.createOpen = false
                this.resetForm()
                window.dispatchEvent(new CustomEvent('toast', { detail: { message } }))
            } catch (error) {
                console.error('Error saving goal:', error)
                this.error = 'Failed to save goal. Please try again.'
            } finally {
                this.loading = false
            }
        },

        async deleteGoal() {
            this.loading = true
            const goal = this.deletingGoal

            try {
                const response = await fetch(
                    `/api/v1/analytics/goals/${goal.id}?website_id=${window.WEBSITE_ID}`,
                    { method: 'DELETE', credentials: 'same-origin' }
                )

                if (!response.ok) {
                    const data = await response.json().catch(() => ({}))
                    window.dispatchEvent(new CustomEvent('toast', {
                        detail: {
                            message: `Failed to delete goal: ${data.detail || 'unknown error'}`,
                            type: 'error',
                        },
                    }))
                    return
                }

                this.goals = this.goals.filter((g) => g.id !== goal.id)
                this.closeDelete()
                window.dispatchEvent(new CustomEvent('toast', {
                    detail: { message: 'Goal deleted successfully' },
                }))
            } catch (error) {
                console.error('Error deleting goal:', error)
                window.dispatchEvent(new CustomEvent('toast', {
                    detail: { message: 'Failed to delete goal. Please try again.', type: 'error' },
                }))
            } finally {
                this.loading = false
            }
        },
    }))

    /**
     * One row of the goals table.
     *
     * The loop variable `goal` is in scope, so this reaches it through `this`
     * and hands the template plain names. The edit and delete buttons do the
     * same thing for the same reason: openEdit(goal) is a call with an
     * argument and cannot appear in an attribute.
     */
    Alpine.data('goalRow', () => ({
        get name() { return this.goal.name },
        get eventName() { return this.goal.event_name },
        get createdAt() {
            return new Date(this.goal.created_at).toLocaleDateString()
        },
        edit() { this.openEdit(this.goal) },
        confirmDelete() { this.openDelete(this.goal) },
    }))
})

document.addEventListener('alpine:init', () => {

    /**
     * A group of tabs, generic enough for every tab strip in the product.
     *
     * The trick that makes one component enough: Alpine injects $el per
     * element, so a getter can read the data attribute of whichever button or
     * panel is asking. `isActive` therefore answers differently for each
     * element while being defined once.
     *
     *   <div x-data="tabs" data-default="top">
     *     <button data-tab="top" @click="select" :class="tabClass">Top</button>
     *     <div data-tab="top" x-show="isActive"> ... </div>
     */
    Alpine.data('tabs', () => ({
        active: '',

        init() { this.active = this.$el.dataset.default || '' },

        select(event) { this.active = event.currentTarget.dataset.tab },

        get isActive() { return this.$el.dataset.tab === this.active },

        get tabClass() {
            return this.$el.dataset.tab === this.active
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
        },
    }))

    /**
     * The date-range menu on the public (shared link) dashboard.
     *
     * The label for the current range is computed here rather than rendered
     * by Jinja into an Alpine string, which is what it used to be: a template
     * literal holding a Jinja if/elif chain, quoted inside an HTML attribute.
     */
    Alpine.data('publicRangeMenu', () => ({
        open: false,
        range: '',

        init() { this.range = this.$el.dataset.range || '7d' },

        toggle() { this.open = !this.open },
        close() { this.open = false },
        get isOpen() { return this.open },

        get rangeText() {
            return {
                '30d': 'Last 30 days',
                '90d': 'Last 90 days',
                '365d': 'Last 12 months',
            }[this.range] || 'Last 7 days'
        },
    }))
})

document.addEventListener('alpine:init', () => {

    /**
     * The team page: who has access, and inviting or removing people.
     *
     * The website id and the current user's address used to be rendered by
     * Jinja straight into the JavaScript. They now arrive as data attributes,
     * which is both required here (a component takes no arguments) and safer:
     * an address containing a quote used to be able to end the expression.
     */
    Alpine.data('teamPage', () => ({
        members: [],
        loading: true,
        error: '',
        userRole: null,
        websiteId: '',
        currentUser: '',
        inviteOpen: false,
        email: '',
        role: 'viewer',
        inviting: false,
        //: The link to send by hand when no invitation email went out, which
        //: is every time on an instance with no email configured.
        inviteLink: '',
        linkCopied: false,

        get inviteEmail() { return modelFor(this, 'email') },
        get inviteRole() { return modelFor(this, 'role') },

        init() {
            this.websiteId = this.$el.dataset.websiteId
            this.currentUser = this.$el.dataset.userEmail
            this.loadMembers()
        },

        get isLoading() { return this.loading },
        get hasError() { return !this.loading && !!this.error },
        get isReady() { return !this.loading && !this.error },
        get memberCount() { return this.members.length },
        get isPlural() { return this.members.length !== 1 },
        get canInvite() {
            return this.userRole === 'owner' || this.userRole === 'admin'
        },
        get isInviteOpen() { return this.inviteOpen },
        get isInviting() { return this.inviting },
        get isNotInviting() { return !this.inviting },
        get submitClass() {
            return this.inviting
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700'
        },
        get adminChoiceClass() {
            return this.role === 'admin' ? 'border-blue-500 bg-blue-50' : ''
        },
        get viewerChoiceClass() {
            return this.role === 'viewer' ? 'border-blue-500 bg-blue-50' : ''
        },

        openInvite() {
            this.inviteLink = ''
            this.inviteOpen = true
        },
        closeInvite() {
            this.inviteOpen = false
            this.inviteLink = ''
        },

        get hasInviteLink() { return !!this.inviteLink },
        get isLinkCopied() { return this.linkCopied },
        get isLinkNotCopied() { return !this.linkCopied },

        copyInviteLink() {
            navigator.clipboard.writeText(this.inviteLink)
            this.linkCopied = true
            setTimeout(() => { this.linkCopied = false }, 2000)
        },

        async loadMembers() {
            this.loading = true
            this.error = ''
            try {
                // Auth via httponly session_token cookie (SameSite=Lax mitigates CSRF)
                const response = await fetch(
                    `/api/v1/websites/${this.websiteId}/members`,
                    { credentials: 'same-origin' }
                )
                const data = await response.json()
                if (!response.ok) {
                    this.error = data.message || data.detail || 'Failed to load team members'
                    return
                }
                this.members = data.members
                const me = this.members.find((m) => m.user_email === this.currentUser)
                if (me) this.userRole = me.role
            } catch (error) {
                console.error('Error loading members:', error)
                this.error = 'Network error. Please try again.'
            } finally {
                this.loading = false
            }
        },

        async inviteMember() {
            if (!this.email) {
                this.notify('Please enter an email address', 'error')
                return
            }
            this.inviting = true
            try {
                const response = await fetch(
                    `/api/v1/websites/${this.websiteId}/members`,
                    {
                        credentials: 'same-origin',
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            email: this.email,
                            role: this.role,
                        }),
                    }
                )
                const data = await response.json()

                if (!response.ok) {
                    this.notify(
                        data.message || data.detail || 'Failed to send invitation',
                        'error'
                    )
                    return
                }

                if (data.invite_url) {
                    // No email went out, so the link has to be shown and kept
                    // on screen. It used to go into a toast that disappeared
                    // after five seconds, taking the only copy with it.
                    this.inviteLink = data.invite_url
                    this.email = ''
                    this.role = 'viewer'
                    await this.loadMembers()
                    return
                }

                this.notify(`Invitation email sent to ${this.email}`)
                this.inviteOpen = false
                this.email = ''
                this.role = 'viewer'
                await this.loadMembers()
            } catch (error) {
                console.error('Error inviting member:', error)
                this.notify('Network error. Please try again.', 'error')
            } finally {
                this.inviting = false
            }
        },

        async removeMember(email) {
            if (!confirm(`Are you sure you want to remove ${email} from the team?`)) {
                return
            }
            try {
                const response = await fetch(
                    `/api/v1/websites/${this.websiteId}/members/${encodeURIComponent(email)}`,
                    { method: 'DELETE', credentials: 'same-origin' }
                )
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}))
                    this.notify(
                        data.message || data.detail || 'Failed to remove member',
                        'error'
                    )
                    return
                }
                this.notify('Team member removed')
                await this.loadMembers()
            } catch (error) {
                console.error('Error removing member:', error)
                this.notify('Network error. Please try again.', 'error')
            }
        },

        async changeRole(email, newRole) {
            try {
                const response = await fetch(
                    `/api/v1/websites/${this.websiteId}/members/${encodeURIComponent(email)}/role`,
                    {
                        credentials: 'same-origin',
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ role: newRole }),
                    }
                )
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}))
                    this.notify(
                        data.message || data.detail || 'Failed to change role',
                        'error'
                    )
                    return
                }
                this.notify('Role changed')
                await this.loadMembers()
            } catch (error) {
                console.error('Error changing role:', error)
                this.notify('Network error. Please try again.', 'error')
            }
        },

        notify(message, type) {
            window.dispatchEvent(
                new CustomEvent('toast', { detail: { message, type: type || 'info' } })
            )
        },
    }))

    /** One row of the team table, flattened for the CSP build. */
    Alpine.data('teamMemberRow', () => ({
        get email() { return this.member.user_email },
        get initial() { return this.member.user_email.charAt(0).toUpperCase() },
        get isYou() { return this.member.user_email === this.currentUser },
        get role() { return this.member.role },
        get status() { return this.member.status },
        get invitedAt() {
            return new Date(this.member.invited_at).toLocaleDateString()
        },
        get invitedBy() { return this.member.invited_by },

        get roleBadgeClass() {
            if (this.member.role === 'owner') return 'bg-purple-100 text-purple-800'
            if (this.member.role === 'admin') return 'bg-blue-100 text-blue-800'
            return 'bg-gray-100 text-gray-800'
        },

        get statusBadgeClass() {
            if (this.member.status === 'active') return 'bg-green-100 text-green-800'
            if (this.member.status === 'pending') return 'bg-yellow-100 text-yellow-800'
            return 'bg-red-100 text-red-800'
        },

        get canChangeRole() {
            return this.userRole === 'owner' && this.member.role !== 'owner'
        },

        get canRemove() {
            if (this.member.role === 'owner') return false
            if (this.userRole === 'owner') return true
            return this.userRole === 'admin' && this.member.role === 'viewer'
        },

        toggleRole() {
            const next = this.member.role === 'admin' ? 'viewer' : 'admin'
            this.changeRole(this.member.user_email, next)
        },

        remove() { this.removeMember(this.member.user_email) },
    }))
})

document.addEventListener('alpine:init', () => {

    /**
     * The small "Copy" buttons.
     *
     * Takes the text from the element named in data-copy-from, so the snippet
     * being copied is the snippet on screen and there is one copy of it. The
     * 404 button used to carry the whole snippet a second time inside its
     * click attribute, as a template literal containing a <script> tag that
     * Jinja rendered a nonce into.
     */
    Alpine.data('copyButton', () => ({
        copied: false,
        get isCopied() { return this.copied },
        get isNotCopied() { return !this.copied },
        copy() {
            const source = document.getElementById(this.$el.dataset.copyFrom)
            const text = source ? source.textContent : (this.$el.dataset.copy || '')
            navigator.clipboard.writeText(text)
            this.copied = true
            setTimeout(() => { this.copied = false }, 2000)
        },
    }))

    /** Domain verification: the DNS record to add, and checking for it. */
    Alpine.data('domainVerification', () => ({
        verified: false,
        verifying: false,
        instructions: null,
        showInstructions: false,
        copied: false,
        websiteId: '',
        domain: '',

        init() {
            this.websiteId = this.$el.dataset.websiteId
            this.domain = this.$el.dataset.domain || ''
            this.verified = this.$el.dataset.verified === 'true'
            this.showInstructions = !this.verified
            if (!this.verified) setTimeout(() => this.fetchInstructions(), 100)
        },

        get isVerifying() { return this.verifying },
        get isNotVerifying() { return !this.verifying },
        get instructionsShown() { return this.showInstructions },
        get instructionsHidden() { return !this.showInstructions },
        get hasInstructions() { return !!this.instructions },
        get hasNoInstructions() { return !this.instructions },
        get showInstructionsPanel() { return this.showInstructions && !this.verified },
        get toggleLabel() {
            return this.showInstructions
                ? 'Hide verification instructions'
                : 'Show verification instructions'
        },
        get recordType() { return this.instructions ? this.instructions.record_type : '' },
        get recordHost() {
            return this.instructions ? this.instructions.dns_record.split('.')[0] : ''
        },
        get recordName() { return this.instructions ? this.instructions.dns_record : '' },
        get recordValue() { return this.instructions ? this.instructions.record_value : '' },
        get bareDomain() {
            return this.domain.replace('https://', '').replace('http://', '')
        },
        get isCopied() { return this.copied },
        get isNotCopied() { return !this.copied },
        get verifyClass() {
            return this.verifying
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-green-600 hover:bg-green-700'
        },

        async toggleInstructions() {
            this.showInstructions = !this.showInstructions
            if (!this.instructions) await this.fetchInstructions()
        },

        copyRecordValue() {
            navigator.clipboard.writeText(this.recordValue)
            this.copied = true
            setTimeout(() => { this.copied = false }, 2000)
        },

        notify(message, type) {
            window.dispatchEvent(
                new CustomEvent('toast', { detail: { message, type: type || 'info' } })
            )
        },

        async fetchInstructions() {
            try {
                // Auth via httponly session_token cookie (SameSite=Lax mitigates CSRF)
                const response = await fetch(
                    `/api/v1/websites/${this.websiteId}/verification-instructions`,
                    { credentials: 'same-origin' }
                )
                const data = await response.json()
                if (!response.ok) {
                    this.notify(
                        `Failed to load instructions: ${data.message || data.detail || 'unknown error'}`,
                        'error'
                    )
                    return
                }
                this.instructions = data
            } catch (error) {
                console.error('Error fetching instructions:', error)
                this.notify('Failed to load verification instructions.', 'error')
            }
        },

        async verifyDomain() {
            this.verifying = true
            try {
                const response = await fetch(
                    `/api/v1/websites/${this.websiteId}/verify-domain`,
                    { method: 'POST', credentials: 'same-origin' }
                )
                const data = await response.json()
                if (!response.ok) {
                    this.notify(data.message || data.detail || 'Something went wrong.', 'error')
                    return
                }
                if (!data.verified) {
                    this.notify(`Verification failed: ${data.message}`, 'error')
                    return
                }
                this.verified = true
                this.showInstructions = false
                this.notify(`${data.message} Tracking is now enabled, reloading…`, 'success')
                setTimeout(() => window.location.reload(), 1500)
            } catch (error) {
                console.error('Error verifying domain:', error)
                this.notify('Failed to verify domain. Please try again.', 'error')
            } finally {
                this.verifying = false
            }
        },
    }))

    /** The public share link and its optional password. */
    Alpine.data('publicSharing', () => ({
        isPublic: false,
        publicUrl: '',
        websiteId: '',
        updating: false,
        linkCopied: false,
        passwordEnabled: false,
        password: '',
        savingPassword: false,

        get newPassword() { return modelFor(this, 'password') },

        init() {
            this.websiteId = this.$el.dataset.websiteId
            this.isPublic = this.$el.dataset.isPublic === 'true'
            this.publicUrl = this.$el.dataset.publicUrl || ''
            this.passwordEnabled = this.$el.dataset.passwordEnabled === 'true'
        },

        get isShared() { return this.isPublic },
        get isNotShared() { return !this.isPublic },
        get isUpdating() { return this.updating },
        get toggleClass() {
            return this.isPublic
                ? 'bg-green-600 hover:bg-green-700'
                : 'bg-gray-200 hover:bg-gray-300'
        },
        get knobClass() {
            return this.isPublic ? 'translate-x-5' : 'translate-x-0'
        },
        get shareUrl() { return this.publicUrl },
        get isLinkCopied() { return this.linkCopied },
        get isLinkNotCopied() { return !this.linkCopied },
        get hasPassword() { return this.passwordEnabled },
        get hasNoPassword() { return !this.passwordEnabled },
        get isSavingPassword() { return this.savingPassword },
        get isNotSavingPassword() { return !this.savingPassword },
        get passwordPlaceholder() {
            return this.passwordEnabled
                ? 'Enter a new password to replace it'
                : 'At least 10 characters, with a digit'
        },
        get passwordButtonLabel() {
            return this.passwordEnabled ? 'Change' : 'Set password'
        },
        get cannotSavePassword() {
            return this.savingPassword || this.password.length === 0
        },

        notify(message, type) {
            window.dispatchEvent(
                new CustomEvent('toast', { detail: { message, type: type || 'info' } })
            )
        },

        copyPublicLink() {
            navigator.clipboard.writeText(this.publicUrl)
            this.linkCopied = true
            setTimeout(() => { this.linkCopied = false }, 2000)
        },

        async togglePublicAccess() {
            this.updating = true
            try {
                const response = await fetch(
                    `/api/v1/websites/${this.websiteId}/public-access`,
                    {
                        method: 'PUT',
                        credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ is_public: !this.isPublic }),
                    }
                )
                const data = await response.json()
                if (!response.ok) {
                    this.notify(data.detail || 'Something went wrong.', 'error')
                    return
                }
                this.isPublic = data.is_public
                if (data.public_url) this.publicUrl = data.public_url
                this.notify(
                    this.isPublic ? 'Public dashboard enabled' : 'Public dashboard disabled',
                    'success'
                )
            } catch (error) {
                console.error('Error toggling public access:', error)
                this.notify('Failed to update public access. Please try again.', 'error')
            } finally {
                this.updating = false
            }
        },

        async setPassword() {
            this.savingPassword = true
            try {
                const response = await fetch('/api/v1/dashboard-password/set', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        website_id: Number(this.websiteId),
                        password: this.password,
                    }),
                })
                const data = await response.json()
                if (!response.ok) {
                    this.notify(
                        data.message || data.detail || 'Could not set the password.',
                        'error'
                    )
                    return
                }
                this.passwordEnabled = true
                this.password = ''
                this.notify('Password protection enabled', 'success')
            } catch (error) {
                console.error('Error setting dashboard password:', error)
                this.notify('Failed to set the password. Please try again.', 'error')
            } finally {
                this.savingPassword = false
            }
        },

        async removePassword() {
            this.savingPassword = true
            try {
                const response = await fetch('/api/v1/dashboard-password/remove', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ website_id: Number(this.websiteId) }),
                })
                const data = await response.json()
                if (!response.ok) {
                    this.notify(
                        data.message || data.detail || 'Could not remove the password.',
                        'error'
                    )
                    return
                }
                this.passwordEnabled = false
                this.notify('Password protection removed', 'success')
            } catch (error) {
                console.error('Error removing dashboard password:', error)
                this.notify('Failed to remove the password. Please try again.', 'error')
            } finally {
                this.savingPassword = false
            }
        },
    }))

    /** Scheduled email reports. */
    Alpine.data('emailReports', () => ({
        reportsOn: false,
        howOften: 'weekly',
        sendTo: '',
        fallbackRecipient: '',
        whichDay: 1,
        websiteId: '',

        get enabled() { return modelFor(this, 'reportsOn') },
        get frequency() { return modelFor(this, 'howOften') },
        get recipient() { return modelFor(this, 'sendTo') },
        get day() { return modelFor(this, 'whichDay') },
        saving: false,
        showSuccess: false,
        errorMessage: '',

        init() {
            const d = this.$el.dataset
            this.websiteId = d.websiteId
            this.reportsOn = d.enabled === 'true'
            this.howOften = d.frequency || 'weekly'
            this.sendTo = d.recipient || ''
            this.fallbackRecipient = d.fallbackRecipient || ''
            this.whichDay = Number(d.day || 1)
        },

        get isEnabled() { return this.reportsOn },
        get isWeekly() { return this.howOften === 'weekly' },
        get isMonthly() { return this.howOften === 'monthly' },
        get isSaving() { return this.saving },
        get isNotSaving() { return !this.saving },
        get hasError() { return !!this.errorMessage },
        get saved() { return this.showSuccess },
        get saveClass() {
            return this.saving
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700'
        },

        get dayOptions() {
            if (this.howOften === 'weekly') {
                return ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
                        'Saturday', 'Sunday'].map((label, i) => ({ value: i + 1, label }))
            }
            return Array.from({ length: 31 }, (_, i) => ({
                value: i + 1,
                label: `Day ${i + 1}`,
            }))
        },

        resetDay() { this.whichDay = 1 },

        async saveEmailReports() {
            this.saving = true
            this.errorMessage = ''
            this.showSuccess = false
            try {
                const response = await fetch(
                    `/api/v1/websites/${this.websiteId}/email-reports`,
                    {
                        method: 'PUT',
                        credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            enabled: this.reportsOn,
                            frequency: this.howOften,
                            recipient: this.sendTo || this.fallbackRecipient,
                            day: parseInt(this.whichDay, 10),
                        }),
                    }
                )
                const data = await response.json()
                if (!response.ok) {
                    this.errorMessage = data.detail || 'Failed to save settings'
                    return
                }
                this.showSuccess = true
                setTimeout(() => { this.showSuccess = false }, 3000)
            } catch (error) {
                console.error('Error saving email reports:', error)
                this.errorMessage = 'Network error. Please try again.'
            } finally {
                this.saving = false
            }
        },
    }))

    /** Traffic spike alerts. */
    Alpine.data('trafficAlerts', () => ({
        alertsOn: false,
        spikeThreshold: 2.0,
        websiteId: '',

        get enabled() { return modelFor(this, 'alertsOn') },
        get threshold() { return modelFor(this, 'spikeThreshold') },
        saving: false,
        showSuccess: false,
        errorMessage: '',

        init() {
            this.websiteId = this.$el.dataset.websiteId
            this.alertsOn = this.$el.dataset.enabled === 'true'
            this.spikeThreshold = Number(this.$el.dataset.threshold || 2.0)
        },

        get isEnabled() { return this.alertsOn },
        get isSaving() { return this.saving },
        get isNotSaving() { return !this.saving },
        get hasError() { return !!this.errorMessage },
        get saved() { return this.showSuccess },
        get percentLabel() { return `${Math.round(this.spikeThreshold * 100)}%` },
        get saveClass() {
            return this.saving
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700'
        },

        async saveAlerts() {
            this.saving = true
            this.errorMessage = ''
            this.showSuccess = false
            try {
                const response = await fetch(
                    `/api/v1/analytics/alerts/${this.websiteId}`,
                    {
                        method: 'PUT',
                        credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            spike_threshold: parseFloat(this.spikeThreshold),
                            email_enabled: this.alertsOn,
                        }),
                    }
                )
                const data = await response.json()
                if (!response.ok) {
                    this.errorMessage =
                        data.message || data.detail || 'Failed to save alert settings'
                    return
                }
                this.showSuccess = true
                setTimeout(() => { this.showSuccess = false }, 3000)
            } catch (error) {
                console.error('Error saving traffic alerts:', error)
                this.errorMessage = 'Network error. Please try again.'
            } finally {
                this.saving = false
            }
        },
    }))

    /** One <option> in the report-day select, flattened for the x-for. */
    Alpine.data('dayOption', () => ({
        get value() { return this.option.value },
        get label() { return this.option.label },
    }))

    /** Deleting a website, gated on typing its name. */
    Alpine.data('deleteWebsite', () => ({
        open: false,
        typedName: '',

        get confirmName() { return modelFor(this, 'typedName') },
        deleting: false,
        error: null,
        expectedName: '',
        websiteId: '',

        init() {
            this.websiteId = this.$el.dataset.websiteId
            const el = document.getElementById('delete-confirm-data')
            this.expectedName = el ? JSON.parse(el.textContent).name : ''
        },

        get isOpen() { return this.open },
        get hasError() { return !!this.error },
        get canDelete() { return this.typedName === this.expectedName },
        get cannotDelete() { return !this.canDelete || this.deleting },
        get deleteLabel() { return this.deleting ? 'Deleting…' : 'Delete website' },
        get deleteClass() {
            return this.canDelete && !this.deleting
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-red-300 cursor-not-allowed'
        },

        openModal() {
            this.typedName = ''
            this.error = null
            this.open = true
        },
        closeModal() { this.open = false },

        async deleteWebsite() {
            if (!this.canDelete) return
            this.deleting = true
            this.error = null
            try {
                const response = await fetch(`/api/v1/websites/${this.websiteId}`, {
                    method: 'DELETE',
                    credentials: 'same-origin',
                })
                if (response.ok) {
                    window.location.href = '/dashboard'
                    return
                }
                const data = await response.json().catch(() => ({}))
                this.error = data.detail || data.message || 'Failed to delete website.'
            } catch (error) {
                console.error('Error deleting website:', error)
                this.error = 'Failed to delete website. Please try again.'
            } finally {
                this.deleting = false
            }
        },
    }))
})

document.addEventListener('alpine:init', () => {

    /**
     * The live debug console: a websocket feed of events as they arrive.
     *
     * The website id used to be rendered by Jinja into the websocket URL
     * inside an inline <script>. It is a data attribute now, which is what the
     * CSP build needs and also removes one more place where a template value
     * was interpolated into JavaScript.
     */
    Alpine.data('debugConsole', () => ({
        ws: null,
        events: [],
        paused: false,
        selectedEvent: null,
        connected: false,
        websiteId: '',

        init() {
            this.websiteId = this.$el.dataset.websiteId
            this.connectWebSocket()
        },

        get connectionLabel() { return this.connected ? 'Connected' : 'Disconnected' },
        get connectionClass() {
            return this.connected
                ? 'bg-green-500 animate-pulse'
                : 'bg-red-500'
        },
        get pauseLabel() { return this.paused ? ' Resume' : ' Pause' },
        get pauseIconClass() { return this.paused ? 'fa-play' : 'fa-pause' },
        get eventCount() { return this.events.length },
        get isEmpty() { return this.events.length === 0 },
        get hasSelection() { return !!this.selectedEvent },
        get selectedJson() {
            return this.selectedEvent
                ? JSON.stringify(this.selectedEvent, null, 2)
                : ''
        },

        connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
            // No credential in the URL: the backend authenticates this
            // same-origin connection via the session cookie sent automatically
            // during the WS handshake (see debug_websocket_endpoint in
            // routers/websocket.py). The public tracking_code was never read
            // by the backend for auth and must not be: it is embedded in every
            // customer page.
            const wsUrl = `${protocol}//${window.location.host}/ws/debug/${this.websiteId}`

            this.ws = new WebSocket(wsUrl)

            this.ws.onopen = () => { this.connected = true }

            this.ws.onmessage = (event) => {
                const message = JSON.parse(event.data)
                if (message.type === 'debug_event' && !this.paused) {
                    this.events.unshift(message.data)
                    if (this.events.length > 100) {
                        this.events = this.events.slice(0, 100)
                    }
                }
            }

            this.ws.onclose = () => {
                this.connected = false
                setTimeout(() => this.connectWebSocket(), 3000)
            }

            this.ws.onerror = (error) => console.error('WebSocket error:', error)
        },

        clearEvents() { this.events = [] },
        togglePause() { this.paused = !this.paused },
        closeDetails() { this.selectedEvent = null },
    }))

    /** One row of the debug feed. */
    Alpine.data('debugEventRow', () => ({
        get time() { return new Date(this.event.timestamp).toLocaleTimeString() },
        get eventType() { return this.event.event_type },
        get path() { return this.event.path },
        get ip() {
            return (this.event.metadata && this.event.metadata.ip) || 'N/A'
        },
        get device() {
            return (this.event.metadata && this.event.metadata.device) || 'N/A'
        },
        get isBot() {
            return !!(this.event.validation && this.event.validation.is_bot)
        },
        get isNotBot() { return !this.isBot },
        showDetails() { this.selectedEvent = this.event },
    }))
})

document.addEventListener('alpine:init', () => {

    /**
     * The funnels page.
     *
     * The stats modal used to reach into funnelStats[selectedFunnel.id].steps
     * from the template. All of that is getters now, which is not only what
     * the CSP build requires: the old expressions indexed the same nested
     * structure four different ways, and one of them (the drop-off) recomputed
     * a neighbouring step's rate inline.
     */
    Alpine.data('funnelsPage', () => ({
        funnels: [],
        funnelStats: {},
        createOpen: false,
        deleteOpen: false,
        statsOpen: false,
        selectedFunnel: null,
        deletingFunnel: null,
        funnelName: '',
        steps: [],
        loading: false,
        statsLoading: false,
        error: null,
        days: 30,

        get formName() { return modelFor(this, 'funnelName') },
        get daysFilter() { return modelFor(this, 'days') },

        init() {
            const el = document.getElementById('funnels-data')
            this.funnels = el ? JSON.parse(el.textContent) : []
            this.resetForm()
            this.loadAllFunnelStats()
        },

        get hasFunnels() { return this.funnels.length > 0 },
        get hasNoFunnels() { return this.funnels.length === 0 },
        get isCreateOpen() { return this.createOpen },
        get isDeleteOpen() { return this.deleteOpen },
        get isStatsOpen() { return this.statsOpen },
        get isLoading() { return this.loading },
        get isNotLoading() { return !this.loading },
        get hasError() { return !!this.error },
        get canRemoveStep() { return this.steps.length > 2 },
        get createClass() {
            return this.loading
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700'
        },
        get deleteClass() {
            return this.loading
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-red-600 hover:bg-red-700'
        },
        get selectedFunnelName() {
            return this.selectedFunnel ? this.selectedFunnel.name : ''
        },
        get deletingFunnelName() {
            return this.deletingFunnel ? this.deletingFunnel.name : ''
        },

        /** The stats for whichever funnel the modal is showing, or null. */
        get currentStats() {
            if (!this.selectedFunnel) return null
            return this.funnelStats[this.selectedFunnel.id] || null
        },
        get statsReady() { return !this.statsLoading && !!this.currentStats },
        get statsEmpty() {
            return (
                !this.statsLoading &&
                !!this.currentStats &&
                (!this.currentStats.steps || this.currentStats.steps.length === 0)
            )
        },
        get statsSteps() {
            const stats = this.currentStats
            if (!stats || !stats.steps) return []
            // Each entry carries what its row needs, including the drop-off
            // against the step before it, so the template never has to look
            // sideways in the array.
            return stats.steps.map((step, index) => ({
                raw: step,
                index,
                number: step.step,
                name: step.name,
                visitors: step.visitors,
                rate: step.conversion_rate.toFixed(1),
                isFirst: index === 0,
                isLast: index === stats.steps.length - 1,
                dropOff: index === 0
                    ? 0
                    : Math.max(
                        0,
                        stats.steps[index - 1].conversion_rate - step.conversion_rate
                    ).toFixed(1),
            }))
        },
        get totalVisitors() {
            return this.currentStats ? this.currentStats.total_visitors : 0
        },
        get overallRate() {
            const steps = this.statsSteps
            return steps.length ? steps[steps.length - 1].rate : '0.0'
        },

        resetForm() {
            this.funnelName = ''
            this.steps = [
                { step: 1, name: '', path: '' },
                { step: 2, name: '', path: '' },
            ]
            this.error = null
        },

        openCreate() {
            this.resetForm()
            this.createOpen = true
        },
        closeCreate() {
            this.createOpen = false
            this.resetForm()
        },
        closeDelete() {
            this.deleteOpen = false
            this.deletingFunnel = null
        },
        closeStats() { this.statsOpen = false },

        addStep() {
            this.steps.push({ step: this.steps.length + 1, name: '', path: '' })
        },

        removeStepAt(index) {
            if (this.steps.length <= 2) return
            this.steps.splice(index, 1)
            this.steps.forEach((step, i) => { step.step = i + 1 })
        },

        openStats(funnel) {
            this.selectedFunnel = funnel
            this.statsOpen = true
            this.loadFunnelStats(funnel.id)
        },

        openDelete(funnel) {
            this.deletingFunnel = funnel
            this.deleteOpen = true
        },

        notify(message, type) {
            window.dispatchEvent(
                new CustomEvent('toast', { detail: { message, type: type || 'info' } })
            )
        },

        async loadAllFunnelStats() {
            for (const funnel of this.funnels) {
                await this.loadFunnelStats(funnel.id, false)
            }
        },

        async loadFunnelStats(funnelId, showModal = true) {
            if (showModal) this.statsLoading = true
            try {
                const response = await fetch(
                    `/api/v1/funnels/${funnelId}/stats?days=${this.days}`,
                    { credentials: 'same-origin' }
                )
                if (response.ok) {
                    this.funnelStats[funnelId] = await response.json()
                }
            } catch (error) {
                console.error('Error loading funnel stats:', error)
            } finally {
                if (showModal) this.statsLoading = false
            }
        },

        /** Reloads the open funnel's stats when the day filter changes. */
        async reloadStats() {
            if (this.selectedFunnel) {
                await this.loadFunnelStats(this.selectedFunnel.id)
            }
        },

        async saveFunnel() {
            this.loading = true
            this.error = null
            try {
                const response = await fetch(
                    `/api/v1/funnels?website_id=${window.WEBSITE_ID}`,
                    {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name: this.funnelName,
                            steps: this.steps,
                        }),
                    }
                )
                const data = await response.json()
                if (!response.ok) {
                    this.error = data.detail || data.message || 'Failed to create funnel'
                    return
                }
                this.funnels.unshift(data)
                this.createOpen = false
                this.resetForm()
                await this.loadFunnelStats(data.id, false)
                this.notify('Funnel created successfully')
            } catch (error) {
                console.error('Error creating funnel:', error)
                this.error = 'Failed to create funnel. Please try again.'
            } finally {
                this.loading = false
            }
        },

        async deleteFunnel() {
            this.loading = true
            const funnel = this.deletingFunnel
            try {
                const response = await fetch(`/api/v1/funnels/${funnel.id}`, {
                    method: 'DELETE',
                    credentials: 'same-origin',
                })
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}))
                    this.notify(
                        `Failed to delete funnel: ${data.detail || 'unknown error'}`,
                        'error'
                    )
                    return
                }
                this.funnels = this.funnels.filter((f) => f.id !== funnel.id)
                delete this.funnelStats[funnel.id]
                this.closeDelete()
                this.notify('Funnel deleted successfully')
            } catch (error) {
                console.error('Error deleting funnel:', error)
                this.notify('Failed to delete funnel. Please try again.', 'error')
            } finally {
                this.loading = false
            }
        },
    }))

    /** One funnel card in the list. */
    Alpine.data('funnelCard', () => ({
        get name() { return this.funnel.name },
        get stepCount() { return this.funnel.steps.length },
        get createdAt() {
            return new Date(this.funnel.created_at).toLocaleDateString()
        },
        get conversionRate() {
            const stats = this.funnelStats[this.funnel.id]
            if (!stats || !stats.steps || stats.steps.length === 0) return '0%'
            const last = stats.steps[stats.steps.length - 1]
            return `${last.conversion_rate.toFixed(1)}%`
        },
        get totalVisitors() {
            const stats = this.funnelStats[this.funnel.id]
            return stats ? stats.total_visitors : 0
        },
        get funnelSteps() {
            return this.funnel.steps.map((step, index) => ({
                raw: step,
                label: `Step ${step.step}`,
                name: step.name,
                path: step.path,
                isLast: index === this.funnel.steps.length - 1,
            }))
        },
        viewStats() { this.openStats(this.funnel) },
        confirmDelete() { this.openDelete(this.funnel) },
    }))

    /** One step shown on a funnel card. */
    Alpine.data('funnelCardStep', () => ({
        get label() { return this.entry.label },
        get name() { return this.entry.name },
        get path() { return this.entry.path },
        get hasNext() { return !this.entry.isLast },
    }))

    /** One step row in the create form, with its two editable fields. */
    Alpine.data('funnelFormStep', () => ({
        get label() { return `Step ${this.step.step}` },
        get stepName() { return modelFor(this.step, 'name') },
        get stepPath() { return modelFor(this.step, 'path') },
        remove() { this.removeStepAt(this.index) },
    }))

    /** One step row in the stats modal. */
    Alpine.data('funnelStatsStep', () => ({
        // An object, not a string. Alpine sets a string style with
        // setAttribute, which style-src 'self' blocks outright, so the bar
        // rendered with no width at all. The object form goes through
        // CSSOM .style.setProperty, which CSP does not gate.
        get barStyle() { return { width: `${this.entry.rate}%` } },
        get number() { return this.entry.number },
        get name() { return this.entry.name },
        get visitors() { return this.entry.visitors },
        get rate() { return this.entry.rate },
        get dropOff() { return this.entry.dropOff },
        get showsDropOff() { return !this.entry.isFirst },
        get hasNext() { return !this.entry.isLast },
    }))
})

document.addEventListener('alpine:init', () => {

    /**
     * The website dashboard's page state: date range, comparison, filters.
     *
     * Filter chips used to call applyFilter('country', value) with arguments.
     * The chip now carries the filter name in a data attribute, which is both
     * what the CSP build needs and a little safer: the value no longer travels
     * through a JavaScript string literal rendered by Jinja.
     */
    Alpine.data('websitePage', () => ({
        state: { range: '7d', compare: false, filters: {} },
        compareOn: false,
        dropdownOpen: false,
        pageTab: 'top',

        get compareEnabled() { return modelFor(this, 'compareOn') },

        init() {
            const el = document.getElementById('page-state-data')
            if (el) this.state = JSON.parse(el.textContent)
            this.compareOn = !!this.state.compare
        },

        get range() { return this.state.range },
        set range(value) { this.state.range = value },
        get filters() { return this.state.filters },
        get properties() { return this.state.filters.properties || {} },

        get propertyChips() {
            return Object.keys(this.properties).map((key) => ({
                key,
                value: this.properties[key],
            }))
        },

        get rangeText() {
            return {
                '30d': 'Last 30 days',
                '90d': 'Last 90 days',
                '365d': 'Last 12 months',
            }[this.range] || 'Last 7 days'
        },

        get isDropdownOpen() { return this.dropdownOpen },
        toggleDropdown() { this.dropdownOpen = !this.dropdownOpen },
        closeDropdown() { this.dropdownOpen = false },

        get rangeClass() {
            return this.$el.dataset.value === this.range
                ? 'bg-blue-50 text-blue-700 border-blue-300'
                : 'bg-white text-gray-700 border-gray-300'
        },

        get tabClass() {
            return this.$el.dataset.tab === this.pageTab
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
        },
        get isTabActive() { return this.$el.dataset.tab === this.pageTab },
        selectTab(event) { this.pageTab = event.currentTarget.dataset.tab },

        get hasCountryFilter() { return !!this.filters.country },
        get hasDeviceFilter() { return !!this.filters.device },
        get hasBrowserFilter() { return !!this.filters.browser },
        get hasPageFilter() { return !!this.filters.page },
        get hasReferrerFilter() { return !!this.filters.referrer },
        get countryFilter() { return this.filters.country },
        get deviceFilter() { return this.filters.device },
        get browserFilter() { return this.filters.browser },
        get pageFilter() { return this.filters.page },
        get referrerFilter() { return this.filters.referrer },
        /** Whether any filter is active at all, for the filter bar. */
        get hasFilters() {
            const f = this.filters
            return !!(
                f.country || f.device || f.browser || f.page || f.referrer ||
                Object.keys(this.properties).length > 0
            )
        },

        get showsFilteredTopPages() {
            return !!this.filters.page && this.pageTab === 'top'
        },

        /**
         * Applies a filter whose name and value are on the clicked element.
         *
         * Used by the server-rendered country, device and browser lists. The
         * value used to be rendered by Jinja into a JavaScript string literal
         * inside the attribute, so a country name containing an apostrophe
         * ended the string.
         */
        applyFilterFromData(event) {
            const el = event.currentTarget
            const name = el.dataset.filter
            this.filters[name] = el.dataset.value !== undefined
                ? el.dataset.value
                : el.dataset[name]
            this.updateDashboard()
        },

        /** Highlights a server-rendered row when its filter is the active one. */
        get serverRowClass() {
            const el = this.$el
            const name = el.dataset.filter
            const value = el.dataset.value !== undefined
                ? el.dataset.value
                : el.dataset[name]
            return this.filters[name] === value
                ? 'bg-blue-50 border-l-4 border-blue-500'
                : ''
        },

        chooseRange(event) {
            this.range = event.currentTarget.dataset.value
            this.dropdownOpen = false
            this.updateDashboard()
        },

        /** Clears the filter named in the button's data-filter. */
        removeFilter(event) {
            this.filters[event.currentTarget.dataset.filter] = ''
            this.updateDashboard()
        },

        applyPropertyFilter(key, value) {
            this.state.filters.properties[key] = value
            this.updateDashboard()
        },

        removePropertyFilter(key) {
            delete this.state.filters.properties[key]
            // Replace the object so Alpine sees the change.
            this.state.filters.properties = { ...this.state.filters.properties }
            this.updateDashboard()
        },

        clearAllFilters() {
            const f = this.state.filters
            f.country = ''
            f.device = ''
            f.browser = ''
            f.page = ''
            f.referrer = ''
            f.properties = {}
            this.updateDashboard()
        },

        updateDashboard() {
            const url = new URL(window.location.href)
            url.searchParams.set('range', this.range)
            url.searchParams.set('compare', this.compareOn ? 'true' : 'false')

            for (const name of ['country', 'device', 'browser', 'page', 'referrer']) {
                const value = this.filters[name]
                if (value) url.searchParams.set(name, value)
                else url.searchParams.delete(name)
            }

            if (Object.keys(this.properties).length > 0) {
                url.searchParams.set('properties', JSON.stringify(this.properties))
            } else {
                url.searchParams.delete('properties')
            }

            window.location.href = url.toString()
        },
    }))

    /** One property filter chip. */
    Alpine.data('propertyChip', () => ({
        get key() { return this.chip.key },
        get value() { return this.chip.value },
        remove() { this.removePropertyFilter(this.chip.key) },
    }))

    /** The "filter by property" dialog. */
    Alpine.data('propertyFilterDialog', () => ({
        open: false,
        key: '',
        value: '',

        get propertyKey() { return modelFor(this, 'key') },
        get propertyValue() { return modelFor(this, 'value') },
        get isOpen() { return this.open },

        toggle() { this.open = !this.open },
        close() { this.open = false },

        addProperty() {
            if (!this.key || !this.value) return
            // applyPropertyFilter lives on the page component, which is up the
            // scope chain. The old code reached for it through
            // $el.closest('[x-data]').__x, an internal Alpine field.
            this.applyPropertyFilter(this.key, this.value)
            this.key = ''
            this.value = ''
            this.open = false
        },
    }))

    /** The anomaly panel. */
    Alpine.data('anomalyPanel', () => ({
        anomalies: [],
        loading: true,
        error: null,
        dismissed: [],
        websiteId: '',

        init() {
            this.websiteId = this.$el.dataset.websiteId
            this.fetchAnomalies()
        },

        get isLoading() { return this.loading },
        get hasError() { return !this.loading && !!this.error },
        get hasAnomalies() {
            return !this.loading && !this.error && this.anomalies.length > 0
        },
        get isEmpty() {
            return !this.loading && !this.error && this.anomalies.length === 0
        },
        get spinnerClass() { return this.loading ? 'animate-spin' : '' },

        get visibleAnomalies() {
            return this.anomalies
                .map((anomaly, index) => ({ anomaly, index }))
                .filter((entry) => !this.dismissed.includes(entry.index))
        },

        async fetchAnomalies() {
            try {
                this.loading = true
                const response = await fetch(`/api/v1/anomalies/${this.websiteId}`)
                const data = await response.json()
                if (response.ok) {
                    this.anomalies = data.anomalies || []
                } else if (response.status === 402) {
                    this.error = 'AI quota exhausted'
                } else {
                    this.error = data.detail || 'Failed to fetch anomalies'
                }
            } catch (err) {
                this.error = 'Network error'
            } finally {
                this.loading = false
            }
        },
    }))

    /** One anomaly card. */
    Alpine.data('anomalyCard', () => ({
        get anomaly() { return this.entry.anomaly },
        get severity() { return this.anomaly.severity },
        get message() { return this.anomaly.message },
        get severityClasses() {
            if (this.severity === 'high') return 'border-red-200 bg-red-50'
            if (this.severity === 'medium') return 'border-yellow-200 bg-yellow-50'
            return 'border-blue-200 bg-blue-50'
        },
        get severityBadgeClasses() {
            if (this.severity === 'high') return 'bg-red-100 text-red-800'
            if (this.severity === 'medium') return 'bg-yellow-100 text-yellow-800'
            return 'bg-blue-100 text-blue-800'
        },
        get severityIcon() {
            if (this.severity === 'high') return '⚠️'
            if (this.severity === 'medium') return '⚡'
            return 'ℹ️'
        },
        get typeLabel() {
            return {
                traffic_spike: 'Traffic Spike',
                bot_attack: 'Bot Attack',
                geographic_anomaly: 'Geographic Anomaly',
                referrer_spam: 'Referrer Spam',
            }[this.anomaly.type] || this.anomaly.type
        },
        get hasPageviews() { return !!this.anomaly.current_pageviews },
        get pageviews() { return this.anomaly.current_pageviews },
        get hasBaseline() { return !!this.anomaly.baseline_avg },
        get baseline() { return this.anomaly.baseline_avg.toFixed(1) },
        get hasSpikeRatio() { return !!this.anomaly.spike_ratio },
        get spikeRatio() { return `${this.anomaly.spike_ratio.toFixed(2)}x` },
        get hasVisitorCount() { return !!this.anomaly.visitor_count },
        get visitorCount() { return this.anomaly.visitor_count },
        get hasCountry() { return !!this.anomaly.country },
        get country() { return this.anomaly.country },
        get hasTimestamp() { return !!this.anomaly.timestamp },
        get timestamp() {
            const date = new Date(this.anomaly.timestamp)
            return date.toLocaleString()
        },
        dismiss() { this.dismissed.push(this.entry.index) },
    }))

    /** The top-pages list, with its share-of-total worked out here. */
    Alpine.data('topPagesList', () => ({
        topPages: [],
        totalPageviews: 0,

        init() {
            const el = document.getElementById('top-pages-data')
            this.topPages = el ? JSON.parse(el.textContent) : []
            this.totalPageviews = Number(this.$el.dataset.totalPageviews || 0)
        },

        get pageRows() {
            return this.topPages.map((page) => ({
                path: page.path,
                views: page.views,
                scroll: page.avg_scroll === null ? '–' : `${page.avg_scroll}% read`,
                share: this.totalPageviews
                    ? `(${Math.round((page.views / this.totalPageviews) * 100)}%)`
                    : '(0%)',
            }))
        },
    }))

    /** The referrers list. */
    Alpine.data('topReferrersList', () => ({
        topReferrers: [],
        totalPageviews: 0,

        init() {
            const el = document.getElementById('top-referrers-data')
            this.topReferrers = el ? JSON.parse(el.textContent) : []
            this.totalPageviews = Number(this.$el.dataset.totalPageviews || 0)
        },

        get referrerRows() {
            return this.topReferrers.map((entry) => ({
                referrer: entry.referrer,
                views: entry.views,
                icon: this.iconFor(entry.referrer),
                share: this.totalPageviews
                    ? `(${Math.round((entry.views / this.totalPageviews) * 100)}%)`
                    : '(0%)',
            }))
        },

        iconFor(referrer) {
            const r = (referrer || '').toLowerCase()
            if (r.includes('google')) return '🔍'
            if (r.includes('facebook') || r.includes('fb.com')) return '📘'
            if (r.includes('twitter') || r.includes('t.co')) return '🐦'
            if (r.includes('linkedin')) return '💼'
            if (r.includes('github')) return '⚙️'
            if (referrer === '(Direct)' || referrer === 'Direct') return '➡️'
            return '🌐'
        },
    }))

    /** A row in either of those two lists. */
    Alpine.data('listRow', () => ({
        /** Clicking a row filters the dashboard by it. */
        applyFilter() {
            const filters = this.filters
            if (this.row.path !== undefined) filters.page = this.row.path
            else filters.referrer = this.row.referrer
            this.updateDashboard()
        },
        get activeClass() {
            const active = this.row.path !== undefined
                ? this.filters.page === this.row.path
                : this.filters.referrer === this.row.referrer
            return active ? 'bg-blue-50 border-blue-200' : ''
        },
        get scrollTitle() {
            return this.row.scroll === '–'
                ? 'no scroll data for this page'
                : 'visitors scrolled this far on average'
        },
        get path() { return this.row.path },
        get referrer() { return this.row.referrer },
        get icon() { return this.row.icon },
        get views() { return this.row.views },
        get scroll() { return this.row.scroll },
        get share() { return this.row.share },
    }))
})
