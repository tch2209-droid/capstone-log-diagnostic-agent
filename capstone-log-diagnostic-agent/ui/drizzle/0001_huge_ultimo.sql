CREATE TABLE `jira_tickets` (
	`ticket_request_id` text PRIMARY KEY NOT NULL,
	`incident_id` text NOT NULL,
	`diagnosis_id` text NOT NULL,
	`status` text DEFAULT 'pending' NOT NULL,
	`jira_issue_id` text,
	`jira_issue_key` text,
	`jira_issue_url` text,
	`last_error` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`incident_id`) REFERENCES `review_items`(`incident_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `jira_tickets_incident_diagnosis_idx` ON `jira_tickets` (`incident_id`,`diagnosis_id`);