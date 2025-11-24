/**
 * ShiftGuard: Google Form Creator Script
 *
 * This script creates the "ShiftGuard: Weekly Availability" Google Form
 * programmatically. The form structure matches the Python backend parsing logic.
 *
 * INSTRUCTIONS:
 * 1. Go to https://script.google.com
 * 2. Create a new project
 * 3. Paste this entire script
 * 4. Click "Run" (select createShiftGuardForm function)
 * 5. Grant permissions when prompted
 * 6. Check the Execution Log for the form URLs
 *
 * Author: ShiftGuard Team
 * Date: 2025-11-23
 */

function createShiftGuardForm() {
  // ============================================
  // STEP 1: Create the Form
  // ============================================
  var form = FormApp.create("ShiftGuard: Weekly Availability");

  // Form description
  form.setDescription(
    "Submit your weekly availability for shift scheduling.\n\n" +
    "Select all shifts you're available to work for each day.\n" +
    "Leave a day blank if you're not available that day.\n\n" +
    "This is your recurring weekly availability - submit once and it applies every week."
  );

  // ============================================
  // STEP 2: Form Settings
  // ============================================
  // Collect email addresses automatically
  form.setCollectEmail(true);

  // Limit to 1 response per user (they can edit later)
  form.setLimitOneResponsePerUser(true);

  // Allow response editing
  form.setAllowResponseEdits(true);

  // Show progress bar
  form.setProgressBar(true);

  // ============================================
  // STEP 3: Section 1 - Checkbox Grid (Weekly Availability)
  // ============================================
  var checkboxGrid = form.addCheckboxGridItem();

  checkboxGrid.setTitle("Weekly Availability");
  checkboxGrid.setHelpText(
    "Check all shifts you can work for each day. " +
    "Leave unchecked if unavailable."
  );

  // Rows: Days of the week
  // CRITICAL: These must match the Python DAY_NAME_TO_NUMBER keys
  var days = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday"
  ];

  // Columns: Shift options
  // CRITICAL: These must match the Python parse_shift_options() patterns
  var shifts = [
    "6:00 AM - 2:00 PM (Open)",
    "2:00 PM - 10:00 PM (Close)"
  ];

  checkboxGrid.setRows(days);
  checkboxGrid.setColumns(shifts);

  // ============================================
  // STEP 4: Section 2 - Notes (Paragraph Text)
  // ============================================
  var notesItem = form.addParagraphTextItem();

  notesItem.setTitle("Notes");
  notesItem.setHelpText(
    "Any specific constraints? (e.g., 'I have class on Tuesday mornings', " +
    "'I prefer closing shifts', 'Available for emergency coverage')"
  );
  notesItem.setRequired(false);

  // ============================================
  // STEP 5: Add a page break with confirmation message
  // ============================================
  form.setConfirmationMessage(
    "Thank you! Your weekly availability has been recorded.\n\n" +
    "You can edit your response anytime by revisiting this form.\n\n" +
    "- ShiftGuard Team"
  );

  // ============================================
  // STEP 6: Output URLs
  // ============================================
  var publishedUrl = form.getPublishedUrl();
  var editUrl = form.getEditUrl();

  Logger.log("============================================");
  Logger.log("ShiftGuard Form Created Successfully!");
  Logger.log("============================================");
  Logger.log("");
  Logger.log("PUBLISHED URL (share with employees):");
  Logger.log(publishedUrl);
  Logger.log("");
  Logger.log("EDIT URL (for form owner):");
  Logger.log(editUrl);
  Logger.log("");
  Logger.log("============================================");
  Logger.log("NEXT STEPS:");
  Logger.log("1. Open the Edit URL to review the form");
  Logger.log("2. Set up the webhook trigger (see setupWebhookTrigger function)");
  Logger.log("3. Share the Published URL with your team");
  Logger.log("============================================");

  // Also show in a popup for convenience
  var ui = FormApp.getUi();
  ui.alert(
    "Form Created!",
    "Published URL:\n" + publishedUrl + "\n\n" +
    "Edit URL:\n" + editUrl + "\n\n" +
    "Check the Execution Log for full details.",
    ui.ButtonSet.OK
  );

  return form;
}


/**
 * Sets up a trigger to send form responses to the ShiftGuard webhook.
 *
 * INSTRUCTIONS:
 * 1. First run createShiftGuardForm() to create the form
 * 2. Update WEBHOOK_URL below with your Vercel deployment URL
 * 3. Run this function to set up the trigger
 */
function setupWebhookTrigger() {
  // ============================================
  // CONFIGURATION - UPDATE THIS!
  // ============================================
  var WEBHOOK_URL = "https://shiftguard.vercel.app/api/v1/availability/webhook";

  // Get the active form (run this from the form's script editor)
  var form = FormApp.getActiveForm();

  if (!form) {
    Logger.log("ERROR: No active form found. Run this from the form's script editor.");
    return;
  }

  // Store webhook URL in script properties
  var scriptProperties = PropertiesService.getScriptProperties();
  scriptProperties.setProperty("WEBHOOK_URL", WEBHOOK_URL);

  // Create trigger for form submissions
  ScriptApp.newTrigger("onFormSubmit")
    .forForm(form)
    .onFormSubmit()
    .create();

  Logger.log("Webhook trigger created successfully!");
  Logger.log("Webhook URL: " + WEBHOOK_URL);
}


/**
 * Handles form submission - sends data to ShiftGuard webhook.
 * This function is called automatically when a form is submitted.
 */
function onFormSubmit(e) {
  var scriptProperties = PropertiesService.getScriptProperties();
  var webhookUrl = scriptProperties.getProperty("WEBHOOK_URL");

  if (!webhookUrl) {
    Logger.log("ERROR: WEBHOOK_URL not configured. Run setupWebhookTrigger first.");
    return;
  }

  // Get form response
  var response = e.response;
  var email = response.getRespondentEmail();
  var itemResponses = response.getItemResponses();

  // Build the payload
  var answers = {};
  var notes = "";

  for (var i = 0; i < itemResponses.length; i++) {
    var itemResponse = itemResponses[i];
    var item = itemResponse.getItem();
    var title = item.getTitle();
    var answer = itemResponse.getResponse();

    if (title === "Weekly Availability") {
      // This is the checkbox grid - answer is a 2D array
      // Rows: days, Columns: shifts selected
      var days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

      for (var j = 0; j < days.length; j++) {
        var dayShifts = answer[j];
        if (dayShifts && dayShifts.length > 0) {
          answers[days[j]] = dayShifts;
        } else {
          answers[days[j]] = [];
        }
      }
    } else if (title === "Notes") {
      notes = answer || "";
    }
  }

  // Create payload matching Python backend format
  var payload = {
    "email": email,
    "answers": answers,
    "notes": notes
  };

  // Send to webhook
  var options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };

  try {
    var httpResponse = UrlFetchApp.fetch(webhookUrl, options);
    var responseCode = httpResponse.getResponseCode();
    var responseBody = httpResponse.getContentText();

    Logger.log("Webhook response: " + responseCode);
    Logger.log("Response body: " + responseBody);

    if (responseCode !== 200) {
      Logger.log("WARNING: Webhook returned non-200 status");
    }
  } catch (error) {
    Logger.log("ERROR sending to webhook: " + error.toString());
  }
}


/**
 * Test function to verify the webhook is working.
 * Sends a test payload to the configured webhook URL.
 */
function testWebhook() {
  var scriptProperties = PropertiesService.getScriptProperties();
  var webhookUrl = scriptProperties.getProperty("WEBHOOK_URL");

  if (!webhookUrl) {
    Logger.log("ERROR: WEBHOOK_URL not configured. Run setupWebhookTrigger first.");
    return;
  }

  // Test payload
  var testPayload = {
    "email": "test@example.com",
    "answers": {
      "Monday": ["6:00 AM - 2:00 PM (Open)", "2:00 PM - 10:00 PM (Close)"],
      "Tuesday": ["6:00 AM - 2:00 PM (Open)"],
      "Wednesday": [],
      "Thursday": ["2:00 PM - 10:00 PM (Close)"],
      "Friday": ["6:00 AM - 2:00 PM (Open)", "2:00 PM - 10:00 PM (Close)"],
      "Saturday": [],
      "Sunday": []
    },
    "notes": "Test submission from Apps Script"
  };

  var options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(testPayload),
    "muteHttpExceptions": true
  };

  try {
    var response = UrlFetchApp.fetch(webhookUrl, options);
    Logger.log("Test webhook response: " + response.getResponseCode());
    Logger.log("Response: " + response.getContentText());
  } catch (error) {
    Logger.log("ERROR: " + error.toString());
  }
}
